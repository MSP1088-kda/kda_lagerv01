from __future__ import annotations

import datetime as dt
import json
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .db import Base


def utcnow():
    # Store naive UTC timestamps for SQLite compatibility.
    return dt.datetime.utcnow().replace(tzinfo=None)


class InstanceConfig(Base):
    __tablename__ = "instance_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    instance_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hostname_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)  # mdns|dns|hosts|none
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    initialized_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ServicePort(Base):
    __tablename__ = "service_ports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(60), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False, default="http")
    exposed: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("service_name", name="uq_service_ports_service"),)


class StoragePath(Base):
    __tablename__ = "storage_paths"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    path: Mapped[str] = mapped_column(String(400), nullable=False)

    __table_args__ = (UniqueConstraint("purpose", name="uq_storage_paths_purpose"),)


class CompanyProfile(Base):
    __tablename__ = "company_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="user")  # admin|user
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transactions = relationship("InventoryTransaction", back_populates="created_by")
    reservations = relationship("Reservation", back_populates="created_by")


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    smtp_host: Mapped[str | None] = mapped_column(String(200), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    smtp_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    smtp_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    imap_host: Mapped[str | None] = mapped_column(String(200), nullable=True)
    imap_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imap_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    imap_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    imap_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)


# --- Catalog domain ---

class Area(Base):
    __tablename__ = "areas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

    device_kinds = relationship("DeviceKind", back_populates="area")


class DeviceKind(Base):
    __tablename__ = "device_kinds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    area = relationship("Area", back_populates="device_kinds")
    device_types = relationship("DeviceType", back_populates="device_kind")

    __table_args__ = (UniqueConstraint("area_id", "name", name="uq_device_kind_area_name"),)


class DeviceType(Base):
    __tablename__ = "device_types"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_kind_id: Mapped[int] = mapped_column(ForeignKey("device_kinds.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    device_kind = relationship("DeviceKind", back_populates="device_types")

    __table_args__ = (UniqueConstraint("device_kind_id", "name", name="uq_device_type_kind_name"),)


class AttributeDef(Base):
    __tablename__ = "attribute_defs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)  # text|number|bool|enum
    enum_options_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list for enum
    is_multi: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scopes = relationship("AttributeScope", back_populates="attribute", cascade="all, delete-orphan")


class AttributeScope(Base):
    __tablename__ = "attribute_scopes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("attribute_defs.id"), nullable=False)
    device_kind_id: Mapped[int | None] = mapped_column(ForeignKey("device_kinds.id"), nullable=True)
    device_type_id: Mapped[int | None] = mapped_column(ForeignKey("device_types.id"), nullable=True)

    attribute = relationship("AttributeDef", back_populates="scopes")

    __table_args__ = (
        CheckConstraint("(device_kind_id IS NOT NULL) OR (device_type_id IS NOT NULL)", name="ck_scope_kind_or_type"),
        Index("ix_scopes_kind", "device_kind_id"),
        Index("ix_scopes_type", "device_type_id"),
    )


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    device_kind_id: Mapped[int | None] = mapped_column(ForeignKey("device_kinds.id"), nullable=True)
    device_type_id: Mapped[int | None] = mapped_column(ForeignKey("device_types.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)  # internal article number
    track_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="serial")  # serial|quantity
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    attribute_values = relationship("ProductAttributeValue", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_products_name", "name"),
        Index("ix_products_sku", "sku"),
    )


class ProductAttributeValue(Base):
    __tablename__ = "product_attribute_values"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("attribute_defs.id"), nullable=False)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)

    product = relationship("Product", back_populates="attribute_values")

    __table_args__ = (UniqueConstraint("product_id", "attribute_id", name="uq_product_attr"),)


# --- Inventory domain ---

class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class StockBalance(Base):
    __tablename__ = "stock_balances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")  # ok|used|defect|bware
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("product_id", "warehouse_id", "condition", name="uq_balance"),)


class StockSerial(Base):
    __tablename__ = "stock_serials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    serial_number: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_stock")  # in_stock|reserved|issued|scrapped

    __table_args__ = (UniqueConstraint("serial_number", name="uq_serial_number"), Index("ix_serial_status", "status"),)


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tx_type: Mapped[str] = mapped_column(String(30), nullable=False)  # receipt|issue|transfer|adjust|scrap
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_from_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    warehouse_to_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    condition: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_by = relationship("User", back_populates="transactions")

    __table_args__ = (Index("ix_tx_created_at", "created_at"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_outbox_created_at", "created_at"),
        Index("ix_outbox_delivered_at", "delivered_at"),
    )


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("stock_serials.id"), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active|released|fulfilled
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_by = relationship("User", back_populates="reservations")

    __table_args__ = (Index("ix_res_status", "status"),)


class SetupState(Base):
    __tablename__ = "setup_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    lock_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lock_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def completed_steps(self) -> list[int]:
        try:
            return list(map(int, json.loads(self.completed_steps_json)))
        except Exception:
            return []

    def set_completed_steps(self, steps: list[int]) -> None:
        self.completed_steps_json = json.dumps(sorted(set(map(int, steps))))
