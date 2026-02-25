from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Product, StockBalance, StockSerial, InventoryTransaction, Reservation


def _get_or_create_balance(db: Session, product_id: int, warehouse_id: int, condition: str) -> StockBalance:
    bal = (
        db.query(StockBalance)
        .filter(StockBalance.product_id == product_id, StockBalance.warehouse_id == warehouse_id, StockBalance.condition == condition)
        .one_or_none()
    )
    if not bal:
        bal = StockBalance(product_id=product_id, warehouse_id=warehouse_id, condition=condition, quantity=0)
        db.add(bal)
        db.flush()
    return bal


def apply_transaction(db: Session, tx: InventoryTransaction, actor_user_id: int | None = None) -> None:
    """
    Applies a transaction to stock tables.
    tx must already be added to db session. This function modifies stock and may raise ValueError.
    """
    product = db.get(Product, tx.product_id)
    if not product:
        raise ValueError("Produkt nicht gefunden")

    mode = product.track_mode

    if mode == "quantity":
        _apply_quantity(db, tx)
    else:
        _apply_serial(db, tx)

    tx.created_by_user_id = actor_user_id
    db.add(tx)


def _apply_quantity(db: Session, tx: InventoryTransaction) -> None:
    qty = int(tx.quantity or 0)
    if qty <= 0:
        raise ValueError("Menge muss > 0 sein")

    if tx.tx_type == "receipt":
        if not tx.warehouse_to_id:
            raise ValueError("Ziel-Lager fehlt")
        bal = _get_or_create_balance(db, tx.product_id, tx.warehouse_to_id, tx.condition)
        bal.quantity += qty
        db.add(bal)
        return

    if tx.tx_type == "issue":
        if not tx.warehouse_from_id:
            raise ValueError("Quell-Lager fehlt")
        bal = _get_or_create_balance(db, tx.product_id, tx.warehouse_from_id, tx.condition)
        if bal.quantity < qty:
            raise ValueError("Nicht genug Bestand")
        bal.quantity -= qty
        db.add(bal)
        _maybe_fulfill_reservations(db, tx)
        return

    if tx.tx_type == "transfer":
        if not tx.warehouse_from_id or not tx.warehouse_to_id:
            raise ValueError("Quelle/Ziel fehlt")
        src = _get_or_create_balance(db, tx.product_id, tx.warehouse_from_id, tx.condition)
        if src.quantity < qty:
            raise ValueError("Nicht genug Bestand in Quelle")
        src.quantity -= qty
        dst = _get_or_create_balance(db, tx.product_id, tx.warehouse_to_id, tx.condition)
        dst.quantity += qty
        db.add_all([src, dst])
        return

    if tx.tx_type == "adjust":
        # interpret as delta (can be positive/negative via note? But keep simple: positive only)
        if not tx.warehouse_to_id:
            raise ValueError("Lager fehlt")
        bal = _get_or_create_balance(db, tx.product_id, tx.warehouse_to_id, tx.condition)
        bal.quantity += qty
        db.add(bal)
        return

    if tx.tx_type == "scrap":
        if not tx.warehouse_from_id:
            raise ValueError("Quell-Lager fehlt")
        bal = _get_or_create_balance(db, tx.product_id, tx.warehouse_from_id, tx.condition)
        if bal.quantity < qty:
            raise ValueError("Nicht genug Bestand")
        bal.quantity -= qty
        db.add(bal)
        return

    raise ValueError("Unbekannter Buchungstyp")


def _apply_serial(db: Session, tx: InventoryTransaction) -> None:
    sn = (tx.serial_number or "").strip()
    if not sn:
        raise ValueError("Seriennummer fehlt")

    if tx.tx_type == "receipt":
        if not tx.warehouse_to_id:
            raise ValueError("Ziel-Lager fehlt")
        existing = db.query(StockSerial).filter(StockSerial.serial_number == sn).one_or_none()
        if existing:
            raise ValueError("Seriennummer existiert bereits")
        s = StockSerial(
            product_id=tx.product_id,
            warehouse_id=tx.warehouse_to_id,
            condition=tx.condition,
            serial_number=sn,
            status="in_stock",
        )
        db.add(s)
        return

    serial = db.query(StockSerial).filter(StockSerial.serial_number == sn).one_or_none()
    if not serial:
        raise ValueError("Seriennummer nicht im Bestand")

    if tx.tx_type == "issue":
        if not tx.warehouse_from_id:
            raise ValueError("Quell-Lager fehlt")
        if serial.warehouse_id != tx.warehouse_from_id:
            raise ValueError("Seriennummer liegt nicht im angegebenen Lager")
        if serial.status not in ("in_stock", "reserved"):
            raise ValueError("Seriennummer ist nicht verfügbar")
        serial.status = "issued"
        db.add(serial)
        _maybe_fulfill_reservations(db, tx, serial_id=serial.id)
        return

    if tx.tx_type == "transfer":
        if not tx.warehouse_from_id or not tx.warehouse_to_id:
            raise ValueError("Quelle/Ziel fehlt")
        if serial.warehouse_id != tx.warehouse_from_id:
            raise ValueError("Seriennummer liegt nicht im Quell-Lager")
        if serial.status != "in_stock":
            raise ValueError("Nur 'in_stock' Seriennummern umlagern")
        serial.warehouse_id = tx.warehouse_to_id
        db.add(serial)
        return

    if tx.tx_type == "scrap":
        if not tx.warehouse_from_id:
            raise ValueError("Quell-Lager fehlt")
        if serial.warehouse_id != tx.warehouse_from_id:
            raise ValueError("Seriennummer liegt nicht im angegebenen Lager")
        if serial.status not in ("in_stock", "reserved"):
            raise ValueError("Seriennummer ist nicht verfügbar")
        serial.status = "scrapped"
        db.add(serial)
        return

    raise ValueError("Unbekannter Buchungstyp für Seriennummer-Artikel")


def _maybe_fulfill_reservations(db: Session, tx: InventoryTransaction, serial_id: int | None = None) -> None:
    """
    Very small helper: if tx.reference matches active reservations, mark them fulfilled (best-effort).
    """
    if not tx.reference:
        return
    q = db.query(Reservation).filter(
        Reservation.status == "active",
        Reservation.product_id == tx.product_id,
        Reservation.warehouse_id == (tx.warehouse_from_id or tx.warehouse_to_id),
        Reservation.reference == tx.reference,
    )
    if serial_id is not None:
        q = q.filter(Reservation.serial_id == serial_id)

    # Fulfill up to qty (quantity mode) or one (serial mode)
    res_list = q.order_by(Reservation.created_at.asc()).all()
    if not res_list:
        return

    remaining = int(tx.quantity or 1)
    for r in res_list:
        if remaining <= 0:
            break
        r.status = "fulfilled"
        db.add(r)
        remaining -= int(r.qty or 1)
