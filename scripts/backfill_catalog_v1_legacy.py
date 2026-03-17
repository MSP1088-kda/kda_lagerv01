#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import sys
from urllib.parse import quote

from sqlalchemy import func

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import get_sessionmaker
from app.models import (
    AssetLinkRule,
    Attachment,
    ImportRowSnapshot,
    ImportRun,
    Manufacturer,
    Product,
    ProductAsset,
)
from app.services.catalog_v1_service import (
    collect_feature_candidates_from_product_assets,
    materialize_product_asset,
    register_existing_product_asset,
    save_import_row_snapshot,
    upsert_product_asset,
)


def _utcnow_naive() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=None)


def _manufacturer_datasheet_source_field(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return "material_no" if value == "material_no" else "sales_name"


def _manufacturer_datasheet_url_template(manufacturer: Manufacturer) -> str:
    prefix = str(getattr(manufacturer, "datasheet_var_1", "") or "").strip()
    mid = str(getattr(manufacturer, "datasheet_var_3", "") or "").strip()
    suffix = str(getattr(manufacturer, "datasheet_var_4", "") or "").strip()
    if not any((prefix, mid, suffix)):
        return ""
    source_field = _manufacturer_datasheet_source_field(getattr(manufacturer, "datasheet_var2_source", "sales_name"))
    placeholder = f"{{{{ {source_field} }}}}"
    return f"{prefix}{placeholder}{mid}{suffix}".strip()


def _build_product_datasheet_url(manufacturer: Manufacturer | None, product: Product | None) -> str:
    if not manufacturer or not product:
        return ""
    prefix = str(getattr(manufacturer, "datasheet_var_1", "") or "").strip()
    mid = str(getattr(manufacturer, "datasheet_var_3", "") or "").strip()
    suffix = str(getattr(manufacturer, "datasheet_var_4", "") or "").strip()
    if not any((prefix, mid, suffix)):
        return ""
    source_field = _manufacturer_datasheet_source_field(getattr(manufacturer, "datasheet_var2_source", "sales_name"))
    raw_value = str(getattr(product, "material_no" if source_field == "material_no" else "sales_name", "") or "").strip()
    if not raw_value:
        fallback_field = "sales_name" if source_field == "material_no" else "material_no"
        raw_value = str(getattr(product, fallback_field, "") or "").strip()
    if not raw_value:
        return ""
    return f"{prefix}{quote(raw_value, safe='')}{mid}{suffix}".strip()


def _legacy_core_payload(product: Product) -> dict[str, object]:
    return {
        "legacy_backfill": True,
        "product_id": int(product.id),
        "name": str(product.name or "").strip() or None,
        "sales_name": str(product.sales_name or "").strip() or None,
        "material_no": str(product.material_no or "").strip() or None,
        "manufacturer_name": str(product.manufacturer_name or "").strip() or None,
        "product_title_1": str(product.product_title_1 or "").strip() or None,
        "product_title_2": str(product.product_title_2 or "").strip() or None,
        "ean": str(product.ean or "").strip() or None,
        "description": str(product.description or "").strip() or None,
    }


def _legacy_external_key(product: Product) -> str:
    for value in (
        str(product.material_no or "").strip(),
        str(product.ean or "").strip(),
        str(product.sales_name or "").strip(),
        str(product.product_title_1 or "").strip(),
        str(product.product_title_2 or "").strip(),
    ):
        if value:
            return value[:220]
    return f"legacy-product-{int(product.id)}"


def _ensure_legacy_asset_link_rules(db) -> int:
    created = 0
    manufacturers = (
        db.query(Manufacturer)
        .filter(
            (func.trim(func.coalesce(Manufacturer.datasheet_var_1, "")) != "")
            | (func.trim(func.coalesce(Manufacturer.datasheet_var_3, "")) != "")
            | (func.trim(func.coalesce(Manufacturer.datasheet_var_4, "")) != "")
        )
        .order_by(Manufacturer.id.asc())
        .all()
    )
    for manufacturer in manufacturers:
        template = _manufacturer_datasheet_url_template(manufacturer)
        if not template:
            continue
        source_field = _manufacturer_datasheet_source_field(getattr(manufacturer, "datasheet_var2_source", "sales_name"))
        existing = (
            db.query(AssetLinkRule)
            .filter(
                AssetLinkRule.manufacturer_id == int(manufacturer.id),
                AssetLinkRule.asset_type == "datasheet_pdf",
                AssetLinkRule.url_template == template,
                AssetLinkRule.source_field == source_field,
            )
            .one_or_none()
        )
        if existing:
            continue
        db.add(
            AssetLinkRule(
                manufacturer_id=int(manufacturer.id),
                asset_type="datasheet_pdf",
                url_template=template,
                source_field=source_field,
                priority=100,
                active=True,
                notes="Backfill aus bestehender Hersteller-Datenblattlogik",
                created_at=_utcnow_naive(),
                updated_at=_utcnow_naive(),
            )
        )
        created += 1
    db.flush()
    return created


def _ensure_legacy_import_run(db) -> ImportRun:
    row = (
        db.query(ImportRun)
        .filter(ImportRun.filename == "legacy_catalog_v1_backfill")
        .order_by(ImportRun.id.desc())
        .first()
    )
    if row:
        return row
    row = ImportRun(
        profile_id=None,
        filename="legacy_catalog_v1_backfill",
        started_at=_utcnow_naive(),
        finished_at=_utcnow_naive(),
        inserted_count=0,
        updated_count=0,
        error_count=0,
        log_text="Legacy-Katalog-V1-Backfill",
    )
    db.add(row)
    db.flush()
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy catalog data into Katalog V1 structures.")
    parser.add_argument("--limit", type=int, default=0, help="Maximale Anzahl Produkte fuer den Lauf.")
    parser.add_argument("--product-id", type=int, default=0, help="Nur ein Produkt backfillen.")
    parser.add_argument("--commit-every", type=int, default=50, help="Commit-Intervall.")
    parser.add_argument(
        "--materialize-documents",
        action="store_true",
        help="Lade vorhandene Datenblatt-URLs direkt lokal herunter und extrahiere Text.",
    )
    parser.add_argument(
        "--materialize-images",
        action="store_true",
        help="Lade erkannte Legacy-Bild-URLs direkt lokal herunter. Standard bleibt lazy.",
    )
    args = parser.parse_args()

    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        created_rules = _ensure_legacy_asset_link_rules(db)
        import_run = _ensure_legacy_import_run(db)

        attachment_rows = (
            db.query(Attachment)
            .filter(Attachment.entity_type == "product_datasheet")
            .order_by(Attachment.entity_id.asc(), Attachment.id.desc())
            .all()
        )
        latest_attachment_by_product: dict[int, Attachment] = {}
        for row in attachment_rows:
            product_id = int(row.entity_id or 0)
            if product_id > 0 and product_id not in latest_attachment_by_product:
                latest_attachment_by_product[product_id] = row

        snapshot_product_ids = {
            int(value)
            for (value,) in db.query(ImportRowSnapshot.product_id)
            .filter(ImportRowSnapshot.product_id.isnot(None))
            .all()
            if int(value or 0) > 0
        }

        products_query = db.query(Product).order_by(Product.id.asc())
        if int(args.product_id or 0) > 0:
            products_query = products_query.filter(Product.id == int(args.product_id))
        if int(args.limit or 0) > 0:
            products_query = products_query.limit(int(args.limit))
        products = products_query.all()

        image_assets_created = 0
        image_assets_materialized = 0
        datasheet_assets_created = 0
        datasheet_urls_created = 0
        datasheet_assets_materialized = 0
        snapshots_created = 0
        candidate_updates = 0
        materialize_failures = 0
        products_marked_legacy = 0
        product_counter = 0

        for product in products:
            product_counter += 1
            if str(product.source_kind or "").strip().lower() != "legacy":
                product.source_kind = "legacy"
                products_marked_legacy += 1
            if int(product.last_import_run_id or 0) <= 0:
                product.last_import_run_id = int(import_run.id)
            if product.last_imported_at is None:
                product.last_imported_at = _utcnow_naive()
            db.add(product)
            existing_assets = {
                (str(row.asset_type or "").strip().lower(), int(row.slot_no or 0) if int(row.slot_no or 0) > 0 else 0): row
                for row in db.query(ProductAsset).filter(ProductAsset.product_id == int(product.id)).all()
            }
            manufacturer = db.get(Manufacturer, int(product.manufacturer_id or 0)) if int(product.manufacturer_id or 0) > 0 else None
            detected_images: dict[str, str] = {}
            detected_documents: dict[str, str] = {}
            product_had_local_text_asset = any(
                bool(str(row.local_path or "").strip()) and bool(str(row.extracted_text or "").strip())
                for row in existing_assets.values()
                if str(row.asset_type or "").strip().lower() in {"datasheet_pdf", "manual_pdf", "energy_label", "other"}
            )

            for idx in range(1, 11):
                raw_url = str(getattr(product, f"image_url_{idx}", "") or "").strip()
                if not raw_url:
                    continue
                detected_images[str(idx)] = raw_url
                asset_key = ("image", int(idx))
                if asset_key in existing_assets:
                    continue
                upsert_product_asset(
                    db,
                    product=product,
                    asset_type="image",
                    slot_no=int(idx),
                    source_url_raw=raw_url,
                    payload=None,
                    mime_type=None,
                    original_name=None,
                    source_kind="legacy",
                    extract_text_enabled=False,
                )
                existing_assets[asset_key] = (
                    db.query(ProductAsset)
                    .filter(
                        ProductAsset.product_id == int(product.id),
                        ProductAsset.asset_type == "image",
                        ProductAsset.slot_no == int(idx),
                    )
                    .order_by(ProductAsset.id.desc())
                    .first()
                )
                image_assets_created += 1
            if args.materialize_images and asset_key in existing_assets:
                image_asset = existing_assets.get(asset_key)
                if image_asset and not str(image_asset.local_path or "").strip() and str(image_asset.source_url_raw or "").strip():
                    try:
                        materialize_product_asset(db, product=product, asset=image_asset)
                        image_assets_materialized += 1
                    except Exception:
                        materialize_failures += 1

            attachment = latest_attachment_by_product.get(int(product.id))
            datasheet_url = _build_product_datasheet_url(manufacturer, product)
            if attachment:
                detected_documents["datasheet_pdf"] = datasheet_url or str(attachment.filename or "")
                if ("datasheet_pdf", 0) not in existing_assets:
                    try:
                        register_existing_product_asset(
                            db,
                            product=product,
                            asset_type="datasheet_pdf",
                            local_path=str(attachment.filename or ""),
                            source_kind="legacy",
                            slot_no=None,
                            source_url_raw=datasheet_url or None,
                            mime_type=str(attachment.mime_type or "") or None,
                            original_name=str(attachment.original_name or "") or None,
                            extract_text_enabled=True,
                        )
                        datasheet_assets_created += 1
                        existing_assets[("datasheet_pdf", 0)] = (
                            db.query(ProductAsset)
                            .filter(
                                ProductAsset.product_id == int(product.id),
                                ProductAsset.asset_type == "datasheet_pdf",
                                ProductAsset.slot_no.is_(None),
                            )
                            .order_by(ProductAsset.id.desc())
                            .first()
                        )
                    except FileNotFoundError:
                        pass
            elif datasheet_url and ("datasheet_pdf", 0) not in existing_assets:
                upsert_product_asset(
                    db,
                    product=product,
                    asset_type="datasheet_pdf",
                    slot_no=None,
                    source_url_raw=datasheet_url,
                    payload=None,
                    mime_type="application/pdf",
                    original_name=Path(datasheet_url).name or None,
                    source_kind="legacy",
                    extract_text_enabled=False,
                )
                existing_assets[("datasheet_pdf", 0)] = (
                    db.query(ProductAsset)
                    .filter(
                        ProductAsset.product_id == int(product.id),
                        ProductAsset.asset_type == "datasheet_pdf",
                        ProductAsset.slot_no.is_(None),
                    )
                    .order_by(ProductAsset.id.desc())
                    .first()
                )
                detected_documents["datasheet_pdf"] = datasheet_url
                datasheet_urls_created += 1
            elif datasheet_url:
                detected_documents["datasheet_pdf"] = datasheet_url

            if args.materialize_documents:
                datasheet_asset = existing_assets.get(("datasheet_pdf", 0))
                if datasheet_asset and not str(datasheet_asset.local_path or "").strip() and str(datasheet_asset.source_url_raw or "").strip():
                    try:
                        materialize_product_asset(db, product=product, asset=datasheet_asset)
                        datasheet_assets_materialized += 1
                    except Exception:
                        materialize_failures += 1

            if int(product.id) not in snapshot_product_ids:
                save_import_row_snapshot(
                    db,
                    import_run_id=int(import_run.id),
                    product_id=int(product.id),
                    manufacturer_id=int(product.manufacturer_id or 0) or None,
                    device_kind_id=int(product.device_kind_id or 0) or None,
                    external_key=_legacy_external_key(product),
                    raw_row={"legacy_backfill": True, "product_id": int(product.id)},
                    normalized_core={key: value for key, value in _legacy_core_payload(product).items() if value not in (None, "", False)},
                    detected_asset_urls={"images": detected_images, "documents": detected_documents},
                    unknown_columns={},
                )
                snapshots_created += 1

            text_asset_rows = (
                db.query(ProductAsset)
                .filter(
                    ProductAsset.product_id == int(product.id),
                    ProductAsset.asset_type.in_(("datasheet_pdf", "manual_pdf", "energy_label", "other")),
                    ProductAsset.extracted_text.isnot(None),
                )
                .count()
            )
            if text_asset_rows > 0 and not product_had_local_text_asset and int(product.device_kind_id or 0) > 0:
                candidate_updates += int(collect_feature_candidates_from_product_assets(db, product=product) or 0)

            if product_counter % max(1, int(args.commit_every or 50)) == 0:
                db.commit()

        import_run.updated_count = int(snapshots_created)
        import_run.finished_at = _utcnow_naive()
        import_run.log_text = (
            f"Legacy-Katalog-V1-Backfill: bilder={image_assets_created}, datenblaetter_lokal={datasheet_assets_created}, "
            f"datenblatt_urls={datasheet_urls_created}, datenblaetter_materialisiert={datasheet_assets_materialized}, "
            f"bilder_materialisiert={image_assets_materialized}, snapshots={snapshots_created}, kandidaten={candidate_updates}, "
            f"regeln={created_rules}, legacy_markiert={products_marked_legacy}, fehler={materialize_failures}"
        )
        db.add(import_run)
        db.commit()

        print("legacy_asset_link_rules_created", created_rules)
        print("image_assets_created", image_assets_created)
        print("image_assets_materialized", image_assets_materialized)
        print("datasheet_assets_created", datasheet_assets_created)
        print("datasheet_urls_created", datasheet_urls_created)
        print("datasheet_assets_materialized", datasheet_assets_materialized)
        print("snapshots_created", snapshots_created)
        print("candidate_updates", candidate_updates)
        print("products_marked_legacy", products_marked_legacy)
        print("materialize_failures", materialize_failures)
        print("processed_products", len(products))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
