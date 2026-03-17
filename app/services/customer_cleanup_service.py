from __future__ import annotations

import datetime as dt
from collections import defaultdict
import re
import time

from sqlalchemy.orm import Session

from ..models import Address as CrmAddress
from ..models import RoleAssignment, ServiceLocation
from .customer_data_quality_service import validate_address


def _clean(value: object | None) -> str:
    return str(value or "").strip()


def _norm(value: object | None) -> str:
    return " ".join(_clean(value).lower().split())


def _usage_rank(value: object | None) -> int:
    usage = _norm(value)
    if usage == "billing":
        return 5
    if usage == "main":
        return 4
    if usage == "service":
        return 3
    if usage == "postal":
        return 2
    if usage:
        return 1
    return 0


def _utcnow_naive() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=None)


def _prepare_address_lookup(row: CrmAddress) -> tuple[str, str, str, str, str]:
    street = _clean(row.street)
    house_no = _clean(row.house_no)
    zip_code = _clean(row.zip_code)
    city = _clean(row.city)
    country_code = _clean(row.country_code).upper() or "DE"
    if street and house_no and _norm(street).endswith(_norm(house_no)):
        trimmed = street[: len(street) - len(house_no)].rstrip(" ,")
        if trimmed:
            street = trimmed
    elif street and not house_no:
        match = re.match(r"^(?P<street>.+?)\s+(?P<house>\d+[A-Za-z0-9./-]*)$", street)
        if match:
            street = _clean(match.group("street"))
            house_no = _clean(match.group("house"))
    return street, house_no, zip_code, city, country_code


def _apply_local_address_cleanup(row: CrmAddress) -> int:
    street, house_no, zip_code, city, country_code = _prepare_address_lookup(row)
    updates = {
        "street": street or None,
        "house_no": house_no or None,
        "zip_code": zip_code or None,
        "city": city or None,
        "country_code": country_code or None,
    }
    updated = 0
    for field_name, next_value in updates.items():
        current_value = _clean(getattr(row, field_name, None)) or None
        if current_value != next_value and (current_value or next_value):
            setattr(row, field_name, next_value)
            updated += 1
    return updated


def _has_address_core(row: CrmAddress) -> bool:
    return any(_clean(value) for value in (row.street, row.house_no, row.zip_code, row.city))


def _validation_signature(row: CrmAddress) -> str:
    return "|".join(
        [
            _norm(row.street),
            _norm(row.house_no),
            _norm(row.zip_code),
            _norm(row.city),
            _norm(row.country_code or "DE"),
        ]
    )


def _address_signature(row: CrmAddress) -> str:
    return "|".join(
        [
            _norm(row.street),
            _norm(row.house_no),
            _norm(row.zip_code),
            _norm(row.city),
            _norm(row.country_code),
            _norm(row.email),
            _norm(row.phone),
        ]
    )


def _preferred_address(rows: list[CrmAddress]) -> CrmAddress:
    return sorted(
        rows,
        key=lambda row: (
            0 if bool(row.is_default) else 1,
            0 if bool(row.active) else 1,
            -_usage_rank(row.usage_type),
            -len(_clean(row.label)),
            int(row.id),
        ),
    )[0]


def _merge_address_values(target: CrmAddress, source: CrmAddress) -> bool:
    changed = False
    for field_name in ("street", "house_no", "zip_code", "city", "country_code", "email", "phone"):
        current_value = _clean(getattr(target, field_name, None))
        source_value = _clean(getattr(source, field_name, None))
        if not current_value and source_value:
            setattr(target, field_name, getattr(source, field_name))
            changed = True
    if len(_clean(source.label)) > len(_clean(target.label)):
        target.label = _clean(source.label) or None
        changed = True
    if _usage_rank(source.usage_type) > _usage_rank(target.usage_type):
        target.usage_type = _clean(source.usage_type) or None
        changed = True
    if bool(source.active) and not bool(target.active):
        target.active = True
        changed = True
    if bool(source.is_default) and not bool(target.is_default):
        target.is_default = True
        changed = True
    return changed


def _apply_address_normalization(row: CrmAddress, result: dict[str, object]) -> dict[str, int | str]:
    status = _clean(result.get("status")).lower()
    row.address_validation_status = status or None
    row.address_validation_message = _clean(result.get("message")) or None
    row.address_validation_source = _clean(result.get("source")) or None
    row.normalized_street = _clean(result.get("normalized_street")) or None
    row.normalized_house_no = _clean(result.get("normalized_house_no")) or None
    row.normalized_zip_code = _clean(result.get("normalized_zip_code")) or None
    row.normalized_city = _clean(result.get("normalized_city")) or None
    row.normalized_country_code = _clean(result.get("normalized_country_code")).upper() or None
    row.address_validated_at = _utcnow_naive() if status else None

    updated = 0
    if status == "valid":
        updates = {
            "street": row.normalized_street,
            "house_no": row.normalized_house_no,
            "zip_code": row.normalized_zip_code,
            "city": row.normalized_city,
            "country_code": row.normalized_country_code,
        }
        for field_name, normalized_value in updates.items():
            current_value = _clean(getattr(row, field_name, None))
            next_value = _clean(normalized_value) or None
            if next_value and current_value != next_value:
                setattr(row, field_name, next_value)
                updated += 1
    return {"status": status, "updated_fields": updated}


def normalize_party_addresses(
    db: Session,
    party_id: int,
    *,
    address_cache: dict[str, dict[str, object]] | None = None,
    delay_seconds: float = 0.0,
) -> dict[str, int]:
    rows = (
        db.query(CrmAddress)
        .filter(CrmAddress.party_id == int(party_id))
        .order_by(CrmAddress.is_default.desc(), CrmAddress.active.desc(), CrmAddress.id.asc())
        .all()
    )
    summary = {
        "checked": 0,
        "normalized": 0,
        "valid": 0,
        "review": 0,
        "invalid": 0,
        "partial": 0,
        "unknown": 0,
        "skipped": 0,
    }
    for row in rows:
        if not _has_address_core(row):
            summary["skipped"] += 1
            continue
        local_updates = _apply_local_address_cleanup(row)
        if local_updates > 0:
            summary["normalized"] += 1
        signature = _validation_signature(row)
        if not signature.strip("|"):
            summary["skipped"] += 1
            continue
        if address_cache is not None and signature in address_cache:
            result = dict(address_cache[signature])
        else:
            street, house_no, zip_code, city, country_code = _prepare_address_lookup(row)
            result = validate_address(
                street=street,
                house_no=house_no,
                zip_code=zip_code,
                city=city,
                country_code=country_code,
            )
            if address_cache is not None:
                address_cache[signature] = dict(result)
            if delay_seconds > 0:
                time.sleep(delay_seconds)
        applied = _apply_address_normalization(row, result)
        db.add(row)
        summary["checked"] += 1
        if int(applied.get("updated_fields") or 0) > 0:
            summary["normalized"] += 1
        status = str(applied.get("status") or "")
        if status in summary:
            summary[status] += 1
    return summary


def dedupe_party_addresses(
    db: Session,
    party_id: int,
    *,
    normalize: bool = False,
    address_cache: dict[str, dict[str, object]] | None = None,
    delay_seconds: float = 0.0,
) -> dict[str, int]:
    rows = (
        db.query(CrmAddress)
        .filter(CrmAddress.party_id == int(party_id))
        .order_by(CrmAddress.is_default.desc(), CrmAddress.active.desc(), CrmAddress.id.asc())
        .all()
    )
    summary = {
        "groups": 0,
        "deleted": 0,
        "relinked_service_locations": 0,
        "relinked_role_assignments": 0,
        "updated": 0,
        "checked": 0,
        "normalized": 0,
        "valid": 0,
        "review": 0,
        "invalid": 0,
        "partial": 0,
        "unknown": 0,
        "skipped": 0,
    }
    if normalize:
        normalization_summary = normalize_party_addresses(
            db,
            int(party_id),
            address_cache=address_cache,
            delay_seconds=delay_seconds,
        )
        for key in ("checked", "normalized", "valid", "review", "invalid", "partial", "unknown", "skipped"):
            summary[key] += int(normalization_summary.get(key) or 0)
        rows = (
            db.query(CrmAddress)
            .filter(CrmAddress.party_id == int(party_id))
            .order_by(CrmAddress.is_default.desc(), CrmAddress.active.desc(), CrmAddress.id.asc())
            .all()
        )
    groups: dict[str, list[CrmAddress]] = defaultdict(list)
    for row in rows:
        signature = _address_signature(row)
        if signature == "||||||":
            continue
        groups[signature].append(row)

    for group_rows in groups.values():
        if len(group_rows) < 2:
            continue
        summary["groups"] += 1
        keeper = _preferred_address(group_rows)
        for row in group_rows:
            if int(row.id) == int(keeper.id):
                continue
            if _merge_address_values(keeper, row):
                summary["updated"] += 1
            service_updates = (
                db.query(ServiceLocation)
                .filter(ServiceLocation.address_id == int(row.id))
                .update({"address_id": int(keeper.id)}, synchronize_session=False)
            )
            role_updates = (
                db.query(RoleAssignment)
                .filter(RoleAssignment.address_id == int(row.id))
                .update({"address_id": int(keeper.id)}, synchronize_session=False)
            )
            summary["relinked_service_locations"] += int(service_updates or 0)
            summary["relinked_role_assignments"] += int(role_updates or 0)
            db.delete(row)
            summary["deleted"] += 1
        db.add(keeper)
    return summary


def dedupe_all_party_addresses(
    db: Session,
    *,
    normalize: bool = False,
    party_limit: int = 0,
    delay_seconds: float = 0.0,
) -> dict[str, int]:
    party_ids = [int(row[0]) for row in db.query(CrmAddress.party_id).distinct().all() if int(row[0] or 0) > 0]
    if int(party_limit or 0) > 0:
        party_ids = party_ids[: int(party_limit)]
    address_cache: dict[str, dict[str, object]] = {}
    summary = {
        "parties_scanned": len(party_ids),
        "parties_changed": 0,
        "groups": 0,
        "deleted": 0,
        "relinked_service_locations": 0,
        "relinked_role_assignments": 0,
        "updated": 0,
        "checked": 0,
        "normalized": 0,
        "valid": 0,
        "review": 0,
        "invalid": 0,
        "partial": 0,
        "unknown": 0,
        "skipped": 0,
    }
    for party_id in party_ids:
        row_summary = dedupe_party_addresses(
            db,
            int(party_id),
            normalize=normalize,
            address_cache=address_cache,
            delay_seconds=delay_seconds,
        )
        if any(
            int(row_summary.get(key) or 0) > 0
            for key in (
                "groups",
                "deleted",
                "updated",
                "relinked_service_locations",
                "relinked_role_assignments",
                "normalized",
            )
        ):
            summary["parties_changed"] += 1
        for key in (
            "groups",
            "deleted",
            "relinked_service_locations",
            "relinked_role_assignments",
            "updated",
            "checked",
            "normalized",
            "valid",
            "review",
            "invalid",
            "partial",
            "unknown",
            "skipped",
        ):
            summary[key] += int(row_summary.get(key) or 0)
    return summary
