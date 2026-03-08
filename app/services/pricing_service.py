from __future__ import annotations

import datetime as dt

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Product, ProductPurchasePrice, Supplier


def get_last_ek(db: Session, product_id: int, supplier_id: int | None = None) -> int | None:
    row = get_last_ek_record(db, product_id=product_id, supplier_id=supplier_id)
    if not row:
        return None
    value = row.effective_unit_cost if row.effective_unit_cost is not None else row.unit_cost
    return int(value) if value is not None else None


def get_last_ek_record(db: Session, product_id: int, supplier_id: int | None = None) -> ProductPurchasePrice | None:
    query = db.query(ProductPurchasePrice).filter(ProductPurchasePrice.product_id == int(product_id))
    if supplier_id is not None:
        query = query.filter(ProductPurchasePrice.supplier_id == int(supplier_id))
    return (
        query.order_by(
            ProductPurchasePrice.effective_date.desc(),
            ProductPurchasePrice.created_at.desc(),
            ProductPurchasePrice.id.desc(),
        )
        .first()
    )


def get_avg_ek(db: Session, product_id: int, supplier_id: int | None = None, weighted: bool = True) -> int | None:
    query = db.query(ProductPurchasePrice).filter(ProductPurchasePrice.product_id == int(product_id))
    if supplier_id is not None:
        query = query.filter(ProductPurchasePrice.supplier_id == int(supplier_id))
    rows = query.filter(ProductPurchasePrice.effective_unit_cost.isnot(None)).all()
    values: list[tuple[int, int]] = []
    for row in rows:
        unit_cost = row.effective_unit_cost if row.effective_unit_cost is not None else row.unit_cost
        if unit_cost is None:
            continue
        qty = int(row.qty or 0) if weighted else 1
        if qty <= 0:
            qty = 1
        values.append((int(unit_cost), qty))
    if not values:
        return None
    if not weighted:
        return int(round(sum(value for value, _qty in values) / len(values)))
    total_qty = sum(qty for _value, qty in values)
    if total_qty <= 0:
        return None
    total_value = sum(value * qty for value, qty in values)
    return int(round(total_value / total_qty))


def get_recent_purchase_prices(db: Session, product_id: int, limit: int = 10) -> list[ProductPurchasePrice]:
    return (
        db.query(ProductPurchasePrice)
        .filter(ProductPurchasePrice.product_id == int(product_id))
        .order_by(
            ProductPurchasePrice.effective_date.desc(),
            ProductPurchasePrice.created_at.desc(),
            ProductPurchasePrice.id.desc(),
        )
        .limit(max(1, int(limit)))
        .all()
    )


def get_product_purchase_summary(db: Session, product_id: int) -> dict[str, object]:
    recent = get_recent_purchase_prices(db, product_id=product_id, limit=10)
    supplier_id = None
    if recent:
        supplier_id = int(recent[0].supplier_id or 0) or None
    supplier = db.get(Supplier, supplier_id) if supplier_id else None
    return {
        "last_ek": get_last_ek(db, product_id=product_id),
        "avg_ek": get_avg_ek(db, product_id=product_id),
        "last_supplier": supplier,
        "recent_prices": recent,
    }


def get_supplier_price_overview(db: Session, supplier_id: int, limit: int = 20) -> list[dict[str, object]]:
    rows = (
        db.query(
            ProductPurchasePrice.product_id.label("product_id"),
            func.max(ProductPurchasePrice.effective_date).label("last_date"),
            func.count(ProductPurchasePrice.id).label("row_count"),
        )
        .filter(ProductPurchasePrice.supplier_id == int(supplier_id))
        .group_by(ProductPurchasePrice.product_id)
        .order_by(func.max(ProductPurchasePrice.effective_date).desc(), ProductPurchasePrice.product_id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    product_ids = [int(row.product_id or 0) for row in rows if int(row.product_id or 0) > 0]
    products = {int(row.id): row for row in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    out: list[dict[str, object]] = []
    for row in rows:
        product_id = int(row.product_id or 0)
        if product_id <= 0:
            continue
        out.append(
            {
                "product": products.get(product_id),
                "last_ek": get_last_ek(db, product_id=product_id, supplier_id=supplier_id),
                "avg_ek": get_avg_ek(db, product_id=product_id, supplier_id=supplier_id),
                "last_date": row.last_date,
                "row_count": int(row.row_count or 0),
            }
        )
    return out
