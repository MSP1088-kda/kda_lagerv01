from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..models import GoodsReceipt, GoodsReceiptLine, Product, SupplierConditionProgress, SupplierConditionSet


def _period_key_for(row: SupplierConditionSet, today: dt.datetime | None = None) -> str:
    base = today or dt.datetime.utcnow().replace(tzinfo=None)
    if row.valid_from:
        return f"{row.valid_from.year}"
    return f"{base.year}"


def _period_bounds(row: SupplierConditionSet, today: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    base = today or dt.datetime.utcnow().replace(tzinfo=None)
    year = row.valid_from.year if row.valid_from else base.year
    start = dt.datetime(year, 1, 1)
    end = dt.datetime(year, 12, 31, 23, 59, 59)
    if row.valid_from and row.valid_from > start:
        start = row.valid_from.replace(tzinfo=None)
    if row.valid_to and row.valid_to < end:
        end = row.valid_to.replace(tzinfo=None)
    if end > base:
        end = base
    return start, end


def _bonus_value(current_value: int, percent: float | None) -> int:
    if not percent:
        return 0
    return int(round(float(current_value or 0) * (float(percent) / 100.0)))


def calculate_condition_progress(db: Session, supplier_id: int | None = None) -> list[dict[str, object]]:
    query = db.query(SupplierConditionSet).filter(SupplierConditionSet.active == True)
    if supplier_id is not None:
        query = query.filter(SupplierConditionSet.supplier_id == int(supplier_id))
    rows = query.order_by(SupplierConditionSet.supplier_id.asc(), SupplierConditionSet.id.desc()).all()
    out: list[dict[str, object]] = []
    now = dt.datetime.utcnow().replace(tzinfo=None)
    for row in rows:
        start, end = _period_bounds(row, today=now)
        period_key = _period_key_for(row, today=now)
        line_query = (
            db.query(GoodsReceiptLine, GoodsReceipt, Product)
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
            .join(Product, Product.id == GoodsReceiptLine.product_id)
            .filter(
                GoodsReceipt.supplier_id == int(row.supplier_id),
                GoodsReceipt.receipt_date >= start,
                GoodsReceipt.receipt_date <= end,
            )
        )
        applies_to = str(row.applies_to or "all").strip().lower()
        if applies_to == "manufacturer" and row.manufacturer_id:
            line_query = line_query.filter(Product.manufacturer_id == int(row.manufacturer_id))
        elif applies_to == "device_kind" and row.device_kind_id:
            line_query = line_query.filter(Product.device_kind_id == int(row.device_kind_id))
        total = 0
        for line, _receipt, _product in line_query.all():
            qty = int(line.qty_received or 0)
            unit_cost = int(line.unit_cost_received or 0)
            total += qty * unit_cost
        target_value = int(row.bonus_target_value or 0)
        current_value = int(total)
        missing_value = max(0, target_value - current_value) if target_value > 0 else 0
        progress_percent = 0.0
        if target_value > 0:
            progress_percent = min(100.0, round((current_value / target_value) * 100.0, 2))
        progress = (
            db.query(SupplierConditionProgress)
            .filter(
                SupplierConditionProgress.condition_set_id == int(row.id),
                SupplierConditionProgress.period_key == period_key,
            )
            .one_or_none()
        )
        if not progress:
            progress = SupplierConditionProgress(condition_set_id=int(row.id), period_key=period_key)
            db.add(progress)
        progress.target_value = target_value or None
        progress.current_value = current_value
        progress.missing_value = missing_value
        progress.last_calculated_at = now
        db.add(progress)
        out.append(
            {
                "condition_set": row,
                "progress": progress,
                "target_value": target_value,
                "current_value": current_value,
                "missing_value": missing_value,
                "progress_percent": progress_percent,
                "bonus_value": _bonus_value(current_value, row.bonus_percent),
                "period_key": period_key,
            }
        )
    db.flush()
    out.sort(key=lambda item: (int(item.get("missing_value") or 0), -int(item.get("current_value") or 0)))
    return out


def get_supplier_condition_summary(db: Session, supplier_id: int) -> dict[str, object]:
    items = calculate_condition_progress(db, supplier_id=supplier_id)
    next_target = items[0] if items else None
    return {
        "items": items,
        "next_target": next_target,
    }
