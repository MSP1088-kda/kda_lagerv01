from __future__ import annotations

import datetime as dt
import json
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
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


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="lesen")  # admin|lagerist|techniker|lesen
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


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("email_accounts.id"), nullable=True)
    to_email: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")  # queued|sent|error
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account = relationship("EmailAccount")

    __table_args__ = (
        Index("ix_email_outbox_status", "status"),
        Index("ix_email_outbox_created_at", "created_at"),
    )


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), nullable=False)
    folder: Mapped[str] = mapped_column(String(120), nullable=False, default="INBOX")
    uid: Mapped[str] = mapped_column(String(120), nullable=False)
    from_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    date_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account = relationship("EmailAccount")

    __table_args__ = (
        UniqueConstraint("account_id", "folder", "uid", name="uq_email_message_uid"),
        Index("ix_email_messages_account_fetched", "account_id", "fetched_at"),
    )


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
    group_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
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


class Manufacturer(Base):
    __tablename__ = "manufacturers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    website: Mapped[str | None] = mapped_column(String(240), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    datasheet_var_1: Mapped[str | None] = mapped_column(String(500), nullable=True)
    datasheet_var_3: Mapped[str | None] = mapped_column(String(500), nullable=True)
    datasheet_var_4: Mapped[str | None] = mapped_column(String(500), nullable=True)
    datasheet_var2_source: Mapped[str] = mapped_column(String(30), nullable=False, default="sales_name")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"), nullable=True)
    device_kind_id: Mapped[int | None] = mapped_column(ForeignKey("device_kinds.id"), nullable=True)
    device_type_id: Mapped[int | None] = mapped_column(ForeignKey("device_types.id"), nullable=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)  # internal article number
    ean: Mapped[str | None] = mapped_column(String(32), nullable=True)
    track_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="quantity")  # quantity
    item_type: Mapped[str] = mapped_column(String(30), nullable=False, default="material")  # appliance|spare_part|accessory|material
    sales_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manufacturer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    material_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_blob: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url_1: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_2: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_3: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_4: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_5: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_6: Mapped[str | None] = mapped_column(String(600), nullable=True)
    sale_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_source: Mapped[str] = mapped_column(String(30), nullable=False, default="manuell")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    manufacturer_ref = relationship("Manufacturer")
    attribute_values = relationship("ProductAttributeValue", back_populates="product", cascade="all, delete-orphan")
    feature_values = relationship("FeatureValue", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_products_name", "name"),
        Index("ix_products_sku", "sku"),
        Index("ix_products_ean", "ean"),
        Index("ix_products_material_no", "material_no"),
        Index("ix_products_active", "active"),
        Index("ix_products_item_type", "item_type"),
        Index("ix_products_active_item_type", "active", "item_type"),
        Index("ix_products_area_kind_type", "area_id", "device_kind_id", "device_type_id"),
        Index("ix_products_manufacturer_id", "manufacturer_id"),
        Index("ix_products_price_source", "price_source"),
        Index("ix_products_search_blob", "search_blob"),
    )


class PriceRuleKind(Base):
    __tablename__ = "price_rule_kinds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_kind_id: Mapped[int] = mapped_column(ForeignKey("device_kinds.id"), nullable=False)
    markup_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    markup_fixed_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rounding_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="none")  # 099|100|none
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("device_kind_id", name="uq_price_rule_kind_device_kind"),
        Index("ix_price_rule_kind_active", "active"),
    )


class ProductLink(Base):
    __tablename__ = "product_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    a_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    b_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    link_type: Mapped[str] = mapped_column(String(40), nullable=False, default="kompatibel")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_productlink_a", "a_product_id"),
        Index("ix_productlink_b", "b_product_id"),
    )


class ProductSet(Base):
    __tablename__ = "product_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_number: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_productset_set_number", "set_number"),
    )


class ProductSetItem(Base):
    __tablename__ = "product_set_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("product_sets.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("set_id", "product_id", name="uq_product_set_item"),
    )


class ProductAttributeValue(Base):
    __tablename__ = "product_attribute_values"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("attribute_defs.id"), nullable=False)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)

    product = relationship("Product", back_populates="attribute_values")

    __table_args__ = (UniqueConstraint("product_id", "attribute_id", name="uq_product_attr"),)


class FeatureDef(Base):
    __tablename__ = "feature_defs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_kind_id: Mapped[int] = mapped_column(ForeignKey("device_kinds.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    label_de: Mapped[str] = mapped_column(String(160), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")  # text|number|bool
    filterable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("device_kind_id", "key", name="uq_featuredef_kind_key"),
        Index("ix_featuredef_kind_filterable", "device_kind_id", "filterable"),
    )


class FeatureValue(Base):
    __tablename__ = "feature_values"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    feature_def_id: Mapped[int] = mapped_column(ForeignKey("feature_defs.id"), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_norm: Mapped[str | None] = mapped_column(Text, nullable=True)

    product = relationship("Product", back_populates="feature_values")
    feature_def = relationship("FeatureDef")

    __table_args__ = (
        UniqueConstraint("product_id", "feature_def_id", name="uq_featurevalue_product_feature"),
        Index("ix_featurevalue_feature", "feature_def_id"),
        Index("ix_featurevalue_product", "product_id"),
        Index("ix_featurevalue_norm", "value_norm"),
        Index("ix_featurevalue_num", "value_num"),
        Index("ix_featurevalue_bool", "value_bool"),
    )


class ImportProfile(Base):
    __tablename__ = "import_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturers.id"), nullable=False)
    device_kind_id: Mapped[int] = mapped_column(ForeignKey("device_kinds.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    delimiter: Mapped[str] = mapped_column(String(5), nullable=False, default=";")
    encoding: Mapped[str] = mapped_column(String(40), nullable=False, default="utf-8")
    has_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ean_column: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("manufacturer_id", "device_kind_id", "name", name="uq_import_profile_mfg_kind_name"),
        Index("ix_import_profile_lookup", "manufacturer_id", "device_kind_id"),
        Index("ix_import_profile_last_used", "last_used_at"),
    )


class ImportProfileMap(Base):
    __tablename__ = "import_profile_maps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("import_profiles.id"), nullable=False)
    map_type: Mapped[str] = mapped_column(String(30), nullable=False)  # product_field|feature
    target_key: Mapped[str] = mapped_column(String(180), nullable=False)
    source_column: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("profile_id", "map_type", "target_key", name="uq_import_profile_map_target"),
        Index("ix_import_profile_map_profile", "profile_id"),
    )


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("import_profiles.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_import_runs_started", "started_at"),
        Index("ix_import_runs_profile", "profile_id"),
    )


class KindListAttribute(Base):
    __tablename__ = "kind_list_attributes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind_id: Mapped[int] = mapped_column(ForeignKey("device_kinds.id"), nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    attribute_def_id: Mapped[int] = mapped_column(ForeignKey("attribute_defs.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("kind_id", "slot", name="uq_kind_list_attribute_slot"),
        Index("ix_kind_list_attribute_kind", "kind_id"),
    )


class ItemTypeFieldRule(Base):
    __tablename__ = "item_type_field_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)  # appliance|spare_part|accessory|material
    field_key: Mapped[str] = mapped_column(String(80), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section: Mapped[str | None] = mapped_column(String(80), nullable=True)
    help_text_de: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("item_type", "field_key", name="uq_item_type_field_rule"),
        Index("ix_item_type_field_rule_order", "item_type", "sort_order"),
    )


# --- Inventory domain ---

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(240), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Owner(Base):
    __tablename__ = "owners"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_owners_active", "active"),
    )


class StockConditionDef(Base):
    __tablename__ = "stock_condition_defs"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label_de: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_stock_condition_sort", "sort_order"),
    )


class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class WarehouseBin(Base):
    __tablename__ = "warehouse_bins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)

    __table_args__ = (
        UniqueConstraint("warehouse_id", "code", name="uq_warehouse_bin_code"),
        Index("ix_warehouse_bins_warehouse", "warehouse_id"),
    )


class StockBalance(Base):
    __tablename__ = "stock_balances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_bins.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id"), nullable=True)
    condition: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")  # ok|used|defect|bware
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_stock_balances_scope", "product_id", "warehouse_id", "condition"),
        Index("ix_stock_balances_bin_id", "bin_id"),
        Index("ix_stock_balances_owner_id", "owner_id"),
    )


class StockSerial(Base):
    __tablename__ = "stock_serials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_bins.id"), nullable=True)
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
    bin_from_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_bins.id"), nullable=True)
    bin_to_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_bins.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id"), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    delivery_note_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_by = relationship("User", back_populates="transactions")
    supplier = relationship("Supplier")

    __table_args__ = (
        Index("ix_tx_created_at", "created_at"),
        Index("ix_tx_supplier_id", "supplier_id"),
        Index("ix_inventory_tx_owner_id", "owner_id"),
    )


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


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)  # repair|product_datasheet
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(400), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(260), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_attachment_entity", "entity_type", "entity_id"),)


class RepairOrder(Base):
    __tablename__ = "repair_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")  # open|in_repair|returned|closed
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    supplier = relationship("Supplier")

    __table_args__ = (Index("ix_repair_order_status", "status"),)


class RepairOrderLine(Base):
    __tablename__ = "repair_order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repair_order_id: Mapped[int] = mapped_column(ForeignKey("repair_orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    warehouse_from_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    warehouse_to_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    condition_in: Mapped[str] = mapped_column(String(40), nullable=False, default="GEBRAUCHT")
    condition_out: Mapped[str] = mapped_column(String(40), nullable=False, default="B_WARE")

    __table_args__ = (Index("ix_repair_order_line_order", "repair_order_id"),)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    po_number: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft|sent|confirmed|received
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier = relationship("Supplier")

    __table_args__ = (
        UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
        Index("ix_purchase_orders_status", "status"),
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expected_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_purchase_order_lines_order", "purchase_order_id"),)


class Stocktake(Base):
    __tablename__ = "stocktakes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_bins.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")  # open|closed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_stocktakes_status", "status"),)


class StocktakeLine(Base):
    __tablename__ = "stocktake_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stocktake_id: Mapped[int] = mapped_column(ForeignKey("stocktakes.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    counted_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_stocktake_lines_stocktake", "stocktake_id"),)


class MinStock(Base):
    __tablename__ = "min_stocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_bins.id"), nullable=True)
    min_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", "bin_id", name="uq_min_stock"),
        Index("ix_min_stocks_wh", "warehouse_id"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiIdempotency(Base):
    __tablename__ = "api_idempotency"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(180), nullable=False)
    route: Mapped[str] = mapped_column(String(180), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("key", "route", name="uq_api_idempotency_key_route"),
        Index("ix_api_idempotency_created_at", "created_at"),
    )


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


class UiPreference(Base):
    __tablename__ = "ui_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pref_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
