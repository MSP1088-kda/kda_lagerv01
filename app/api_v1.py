from __future__ import annotations

import datetime as dt
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .db import db_session
from .models import (
    Area,
    AttributeDef,
    AttributeScope,
    DeviceKind,
    DeviceType,
    InventoryTransaction,
    OutboxEvent,
    Product,
    ProductAttributeValue,
    StockBalance,
    StockSerial,
    Warehouse,
)
from .security import require_api_key, require_api_or_user

router = APIRouter(prefix="/api/v1", tags=["api-v1"], dependencies=[Depends(require_api_or_user)])


class MetaOut(BaseModel):
    version: str
    build: str
    git_sha: str
    build_date: str


class AreaOut(BaseModel):
    id: int
    name: str


class KindOut(BaseModel):
    id: int
    area_id: int
    name: str


class TypeOut(BaseModel):
    id: int
    device_kind_id: int
    name: str


class AttributeOut(BaseModel):
    id: int
    name: str
    slug: str
    value_type: str
    is_multi: bool
    enum_options: list[str]
    scope_kind_ids: list[int]
    scope_type_ids: list[int]


class ProductOut(BaseModel):
    id: int
    area_id: Optional[int]
    device_kind_id: Optional[int]
    device_type_id: Optional[int]
    name: str
    manufacturer: Optional[str]
    sku: Optional[str]
    track_mode: str
    description: Optional[str]
    active: bool


class ProductAttributeValueOut(BaseModel):
    attribute_id: int
    attribute_name: str
    attribute_slug: str
    value_type: str
    value_text: str


class ProductDetailOut(ProductOut):
    attributes: list[ProductAttributeValueOut]


class WarehouseOut(BaseModel):
    id: int
    name: str
    description: Optional[str]


class StockQtyLineOut(BaseModel):
    product_id: int
    warehouse_id: int
    condition: str
    quantity: int


class StockSerialSummaryOut(BaseModel):
    product_id: int
    warehouse_id: int
    condition: str
    total: int
    in_stock: int
    reserved: int
    issued: int
    scrapped: int


class StockOut(BaseModel):
    qty_lines: list[StockQtyLineOut]
    serials: list[StockSerialSummaryOut]


class TransactionOut(BaseModel):
    id: int
    tx_type: str
    product_id: int
    warehouse_from_id: Optional[int]
    warehouse_to_id: Optional[int]
    condition: str
    quantity: int
    serial_number: Optional[str]
    reference: Optional[str]
    note: Optional[str]
    created_at: Optional[str]
    created_by_user_id: Optional[int]


class EventOut(BaseModel):
    id: int
    event_type: str
    entity_type: str
    entity_id: int
    aggregate_type: str
    aggregate_id: int
    payload: dict
    created_at: Optional[str]
    delivered_at: Optional[str]
    delivery_attempts: int


class EventAckOut(BaseModel):
    id: int
    delivered: bool
    delivered_at: Optional[str]


class EventAckIn(BaseModel):
    event_id: Optional[int] = None
    up_to_id: Optional[int] = None


@router.get("/meta", response_model=MetaOut)
def api_meta(request: Request):
    meta = getattr(request.app.state, "version_meta", None)
    if isinstance(meta, dict):
        return meta
    return {"version": "0.0.0", "build": "unknown", "git_sha": "unknown", "build_date": "unknown"}


@router.get("/catalog/areas", response_model=list[AreaOut])
def api_catalog_areas(db: Session = Depends(db_session)):
    return db.query(Area).order_by(Area.name.asc()).all()


@router.get("/catalog/kinds", response_model=list[KindOut])
def api_catalog_kinds(area_id: int = 0, db: Session = Depends(db_session)):
    q = db.query(DeviceKind)
    if area_id:
        q = q.filter(DeviceKind.area_id == area_id)
    return q.order_by(DeviceKind.name.asc()).all()


@router.get("/catalog/types", response_model=list[TypeOut])
def api_catalog_types(kind_id: int = 0, db: Session = Depends(db_session)):
    q = db.query(DeviceType)
    if kind_id:
        q = q.filter(DeviceType.device_kind_id == kind_id)
    return q.order_by(DeviceType.name.asc()).all()


@router.get("/catalog/attributes", response_model=list[AttributeOut])
def api_catalog_attributes(kind_id: int = 0, type_id: int = 0, db: Session = Depends(db_session)):
    q = db.query(AttributeDef)
    if kind_id or type_id:
        q = q.join(AttributeScope, AttributeScope.attribute_id == AttributeDef.id)
        conds = []
        if kind_id:
            conds.append(AttributeScope.device_kind_id == kind_id)
        if type_id:
            conds.append(AttributeScope.device_type_id == type_id)
        q = q.filter(or_(*conds)).distinct()

    attrs = q.order_by(AttributeDef.name.asc()).all()
    if not attrs:
        return []

    attr_ids = [a.id for a in attrs]
    scopes = db.query(AttributeScope).filter(AttributeScope.attribute_id.in_(attr_ids)).all()

    scope_kind_map: dict[int, list[int]] = {aid: [] for aid in attr_ids}
    scope_type_map: dict[int, list[int]] = {aid: [] for aid in attr_ids}

    for s in scopes:
        if s.device_kind_id:
            scope_kind_map[s.attribute_id].append(s.device_kind_id)
        if s.device_type_id:
            scope_type_map[s.attribute_id].append(s.device_type_id)

    out: list[AttributeOut] = []
    for a in attrs:
        enum_options = []
        if a.enum_options_json:
            try:
                parsed = json.loads(a.enum_options_json)
                if isinstance(parsed, list):
                    enum_options = [str(v) for v in parsed]
            except Exception:
                enum_options = []
        out.append(
            AttributeOut(
                id=a.id,
                name=a.name,
                slug=a.slug,
                value_type=a.value_type,
                is_multi=bool(a.is_multi),
                enum_options=enum_options,
                scope_kind_ids=sorted(set(scope_kind_map.get(a.id, []))),
                scope_type_ids=sorted(set(scope_type_map.get(a.id, []))),
            )
        )
    return out


@router.get("/products", response_model=list[ProductOut])
def api_products(
    q: str = "",
    area_id: int = 0,
    kind_id: int = 0,
    type_id: int = 0,
    db: Session = Depends(db_session),
):
    query = db.query(Product).filter(Product.active == True)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.manufacturer.ilike(like)))
    if area_id:
        query = query.filter(Product.area_id == area_id)
    if kind_id:
        query = query.filter(Product.device_kind_id == kind_id)
    if type_id:
        query = query.filter(Product.device_type_id == type_id)
    return query.order_by(Product.id.desc()).limit(200).all()


@router.get("/products/{product_id}", response_model=ProductDetailOut)
def api_product_detail(product_id: int, db: Session = Depends(db_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    rows = (
        db.query(ProductAttributeValue, AttributeDef)
        .join(AttributeDef, AttributeDef.id == ProductAttributeValue.attribute_id)
        .filter(ProductAttributeValue.product_id == product_id)
        .order_by(AttributeDef.name.asc())
        .all()
    )
    attrs = [
        ProductAttributeValueOut(
            attribute_id=attr.id,
            attribute_name=attr.name,
            attribute_slug=attr.slug,
            value_type=attr.value_type,
            value_text=pav.value_text,
        )
        for pav, attr in rows
    ]

    return ProductDetailOut(
        id=p.id,
        area_id=p.area_id,
        device_kind_id=p.device_kind_id,
        device_type_id=p.device_type_id,
        name=p.name,
        manufacturer=p.manufacturer,
        sku=p.sku,
        track_mode=p.track_mode,
        description=p.description,
        active=bool(p.active),
        attributes=attrs,
    )


@router.get("/warehouses", response_model=list[WarehouseOut])
def api_warehouses(db: Session = Depends(db_session)):
    return db.query(Warehouse).order_by(Warehouse.name.asc()).all()


@router.get("/stock", response_model=StockOut)
def api_stock(product_id: int = 0, warehouse_id: int = 0, db: Session = Depends(db_session)):
    bal_q = db.query(StockBalance)
    serial_q = db.query(StockSerial)

    if product_id:
        bal_q = bal_q.filter(StockBalance.product_id == product_id)
        serial_q = serial_q.filter(StockSerial.product_id == product_id)
    if warehouse_id:
        bal_q = bal_q.filter(StockBalance.warehouse_id == warehouse_id)
        serial_q = serial_q.filter(StockSerial.warehouse_id == warehouse_id)

    qty_lines = [
        StockQtyLineOut(
            product_id=b.product_id,
            warehouse_id=b.warehouse_id,
            condition=b.condition,
            quantity=b.quantity,
        )
        for b in bal_q.order_by(StockBalance.product_id.asc(), StockBalance.warehouse_id.asc(), StockBalance.condition.asc()).all()
    ]

    serial_summary: dict[tuple[int, int, str], dict[str, int]] = {}
    for s in serial_q.all():
        key = (s.product_id, s.warehouse_id, s.condition)
        row = serial_summary.setdefault(
            key,
            {"total": 0, "in_stock": 0, "reserved": 0, "issued": 0, "scrapped": 0},
        )
        row["total"] += 1
        if s.status in row:
            row[s.status] += 1

    serials = [
        StockSerialSummaryOut(
            product_id=key[0],
            warehouse_id=key[1],
            condition=key[2],
            total=vals["total"],
            in_stock=vals["in_stock"],
            reserved=vals["reserved"],
            issued=vals["issued"],
            scrapped=vals["scrapped"],
        )
        for key, vals in sorted(serial_summary.items())
    ]

    return StockOut(qty_lines=qty_lines, serials=serials)


@router.get("/transactions", response_model=list[TransactionOut])
def api_transactions(
    product_id: int = 0,
    warehouse_id: int = 0,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(db_session),
):
    q = db.query(InventoryTransaction)
    if product_id:
        q = q.filter(InventoryTransaction.product_id == product_id)
    if warehouse_id:
        q = q.filter(
            or_(
                InventoryTransaction.warehouse_from_id == warehouse_id,
                InventoryTransaction.warehouse_to_id == warehouse_id,
            )
        )

    rows = q.order_by(InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc()).limit(limit).all()
    return [
        TransactionOut(
            id=r.id,
            tx_type=r.tx_type,
            product_id=r.product_id,
            warehouse_from_id=r.warehouse_from_id,
            warehouse_to_id=r.warehouse_to_id,
            condition=r.condition,
            quantity=r.quantity,
            serial_number=r.serial_number,
            reference=r.reference,
            note=r.note,
            created_at=r.created_at.isoformat() if r.created_at else None,
            created_by_user_id=r.created_by_user_id,
        )
        for r in rows
    ]


@router.get("/events", response_model=list[EventOut])
def api_events(
    after_id: int = 0,
    limit: int = Query(default=200, ge=1, le=500),
    _api=Depends(require_api_key),
    db: Session = Depends(db_session),
):
    q = db.query(OutboxEvent)
    if after_id:
        q = q.filter(OutboxEvent.id > after_id)

    rows = q.order_by(OutboxEvent.id.asc()).limit(limit).all()
    for row in rows:
        if row.delivered_at is None:
            row.delivery_attempts = int(row.delivery_attempts or 0) + 1
            db.add(row)
    if rows:
        db.commit()

    out: list[EventOut] = []
    for row in rows:
        payload = {}
        try:
            parsed = json.loads(row.payload_json)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
        out.append(
            EventOut(
                id=row.id,
                event_type=row.event_type,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                aggregate_type=row.entity_type,
                aggregate_id=row.entity_id,
                payload=payload,
                created_at=row.created_at.isoformat() if row.created_at else None,
                delivered_at=row.delivered_at.isoformat() if row.delivered_at else None,
                delivery_attempts=row.delivery_attempts,
            )
        )
    return out


@router.post("/events/{event_id}/ack", response_model=EventAckOut)
def api_event_ack(event_id: int, _api=Depends(require_api_key), db: Session = Depends(db_session)):
    event = db.get(OutboxEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.delivered_at is None:
        event.delivered_at = dt.datetime.utcnow().replace(tzinfo=None)
        db.add(event)
        db.commit()
        db.refresh(event)
    return EventAckOut(
        id=event.id,
        delivered=event.delivered_at is not None,
        delivered_at=event.delivered_at.isoformat() if event.delivered_at else None,
    )


@router.post("/events/ack")
def api_event_ack_bulk(payload: EventAckIn, _api=Depends(require_api_key), db: Session = Depends(db_session)):
    now = dt.datetime.utcnow().replace(tzinfo=None)
    acked = 0
    if payload.event_id:
        event = db.get(OutboxEvent, int(payload.event_id))
        if event and event.delivered_at is None:
            event.delivered_at = now
            db.add(event)
            acked = 1
    elif payload.up_to_id:
        rows = db.query(OutboxEvent).filter(OutboxEvent.id <= int(payload.up_to_id), OutboxEvent.delivered_at.is_(None)).all()
        for row in rows:
            row.delivered_at = now
            db.add(row)
        acked = len(rows)
    else:
        raise HTTPException(status_code=400, detail="event_id oder up_to_id erforderlich")
    db.commit()
    return {"status": "ok", "acked": acked}
