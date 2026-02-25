from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AttributeDef, AttributeScope, Product, ProductAttributeValue


def get_applicable_attributes(db: Session, device_kind_id: int | None, device_type_id: int | None) -> list[AttributeDef]:
    q = db.query(AttributeDef).join(AttributeScope, AttributeScope.attribute_id == AttributeDef.id)
    clauses = []
    if device_type_id:
        clauses.append(AttributeScope.device_type_id == device_type_id)
    if device_kind_id:
        clauses.append(AttributeScope.device_kind_id == device_kind_id)
    if not clauses:
        return []
    q = q.filter(__or__(*clauses)).distinct().order_by(AttributeDef.name.asc())
    return q.all()


def __or__(*conds):
    from sqlalchemy import or_
    return or_(*conds)


def set_product_attribute_value(db: Session, product_id: int, attribute_id: int, value_text: str) -> None:
    pav = (
        db.query(ProductAttributeValue)
        .filter(ProductAttributeValue.product_id == product_id, ProductAttributeValue.attribute_id == attribute_id)
        .one_or_none()
    )
    if pav:
        pav.value_text = value_text
        db.add(pav)
    else:
        db.add(ProductAttributeValue(product_id=product_id, attribute_id=attribute_id, value_text=value_text))
