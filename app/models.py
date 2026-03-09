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
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("mail_threads.id"), nullable=True)
    mail_message_id: Mapped[int | None] = mapped_column(ForeignKey("email_messages.id"), nullable=True)
    to_email: Mapped[str] = mapped_column(String(200), nullable=False)
    cc_emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    bcc_emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), nullable=True)
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
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("mail_threads.id"), nullable=True)
    folder: Mapped[str] = mapped_column(String(120), nullable=False, default="INBOX")
    uid: Mapped[str] = mapped_column(String(120), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="in")
    message_id_header: Mapped[str | None] = mapped_column(String(400), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(400), nullable=True)
    references_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    cc_emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    bcc_emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    date_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unassigned")
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), nullable=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account = relationship("EmailAccount")

    __table_args__ = (
        UniqueConstraint("account_id", "folder", "uid", name="uq_email_message_uid"),
        Index("ix_email_messages_account_fetched", "account_id", "fetched_at"),
        Index("ix_email_messages_thread", "thread_id"),
        Index("ix_email_messages_assignment", "assignment_status"),
        Index("ix_email_messages_message_id_header", "message_id_header"),
    )


class MailThread(Base):
    __tablename__ = "mail_threads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_normalized: Mapped[str] = mapped_column(String(300), nullable=False)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    last_message_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_mail_threads_subject", "subject_normalized"),
        Index("ix_mail_threads_customer", "master_customer_id"),
        Index("ix_mail_threads_case", "case_id"),
        Index("ix_mail_threads_last_message_at", "last_message_at"),
    )


class MailAttachment(Base):
    __tablename__ = "mail_attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mail_message_id: Mapped[int] = mapped_column(ForeignKey("email_messages.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_path: Mapped[str] = mapped_column(String(600), nullable=False)
    paperless_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_mail_attachments_message", "mail_message_id"),
        Index("ix_mail_attachments_paperless", "paperless_document_id"),
    )


class MailTemplate(Base):
    __tablename__ = "mail_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_template: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("template_key", name="uq_mail_templates_template_key"),
        Index("ix_mail_templates_active", "active"),
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
    product_title_1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product_title_2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    material_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_blob: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_1: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_2: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_3: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_4: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_5: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_6: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_7: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_8: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_9: Mapped[str | None] = mapped_column(String(600), nullable=True)
    image_url_10: Mapped[str | None] = mapped_column(String(600), nullable=True)
    sale_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_source: Mapped[str] = mapped_column(String(30), nullable=False, default="manuell")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    manufacturer_ref = relationship("Manufacturer")
    attribute_values = relationship("ProductAttributeValue", back_populates="product", cascade="all, delete-orphan")
    feature_values = relationship("FeatureValue", back_populates="product", cascade="all, delete-orphan")
    accessory_links = relationship(
        "ProductAccessoryLink",
        foreign_keys="ProductAccessoryLink.product_id",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    accessory_linked_from = relationship(
        "ProductAccessoryLink",
        foreign_keys="ProductAccessoryLink.accessory_product_id",
        back_populates="accessory_product",
    )
    accessory_references = relationship(
        "ProductAccessoryReference",
        foreign_keys="ProductAccessoryReference.product_id",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    accessory_matched_references = relationship(
        "ProductAccessoryReference",
        foreign_keys="ProductAccessoryReference.matched_product_id",
        back_populates="matched_product",
    )

    __table_args__ = (
        Index("ix_products_name", "name"),
        Index("ix_products_sku", "sku"),
        Index("ix_products_ean", "ean"),
        Index("ix_products_material_no", "material_no"),
        Index("ix_products_active", "active"),
        Index("ix_products_item_type", "item_type"),
        Index("ix_products_device_kind_id", "device_kind_id"),
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


class FeatureOption(Base):
    __tablename__ = "feature_options"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_def_id: Mapped[int] = mapped_column(ForeignKey("feature_defs.id"), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(160), nullable=False)
    label_de: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    feature_def = relationship("FeatureDef")
    aliases = relationship("FeatureOptionAlias", back_populates="option", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("feature_def_id", "canonical_key", name="uq_feature_option_canonical"),
        Index("ix_feature_option_feature_active", "feature_def_id", "active"),
        Index("ix_feature_option_feature_sort", "feature_def_id", "sort_order"),
    )


class FeatureOptionAlias(Base):
    __tablename__ = "feature_option_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("feature_options.id"), nullable=False)
    alias_text: Mapped[str] = mapped_column(String(220), nullable=False)
    alias_norm: Mapped[str] = mapped_column(String(220), nullable=False)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    option = relationship("FeatureOption", back_populates="aliases")
    manufacturer_ref = relationship("Manufacturer")

    __table_args__ = (
        UniqueConstraint("option_id", "alias_text", "manufacturer_id", name="uq_feature_option_alias"),
        Index("ix_feature_option_alias_option", "option_id"),
        Index("ix_feature_option_alias_norm", "alias_norm"),
        Index("ix_feature_option_alias_manufacturer", "manufacturer_id"),
    )


class FeatureValue(Base):
    __tablename__ = "feature_values"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    feature_def_id: Mapped[int] = mapped_column(ForeignKey("feature_defs.id"), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_id: Mapped[int | None] = mapped_column(ForeignKey("feature_options.id"), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_norm: Mapped[str | None] = mapped_column(Text, nullable=True)

    product = relationship("Product", back_populates="feature_values")
    feature_def = relationship("FeatureDef")
    option = relationship("FeatureOption")

    __table_args__ = (
        UniqueConstraint("product_id", "feature_def_id", name="uq_featurevalue_product_feature"),
        Index("ix_featurevalue_feature", "feature_def_id"),
        Index("ix_featurevalue_product", "product_id"),
        Index("ix_featurevalue_option", "option_id"),
        Index("ix_featurevalue_feature_option", "feature_def_id", "option_id"),
        Index("ix_featurevalue_norm", "value_norm"),
        Index("ix_featurevalue_num", "value_num"),
        Index("ix_featurevalue_bool", "value_bool"),
        Index("ix_featurevalue_feature_text", "feature_def_id", "value_text"),
        Index("ix_featurevalue_feature_num", "feature_def_id", "value_num"),
        Index("ix_featurevalue_feature_bool", "feature_def_id", "value_bool"),
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
    map_type: Mapped[str] = mapped_column(String(30), nullable=False)  # product_field|feature|accessory
    target_key: Mapped[str] = mapped_column(String(180), nullable=False)
    source_column: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # feature-type or accessory separator_mode

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


class ImportDraft(Base):
    __tablename__ = "import_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="uploaded")
    filename_original: Mapped[str | None] = mapped_column(String(260), nullable=True)
    file_path_tmp: Mapped[str | None] = mapped_column(String(600), nullable=True)
    delimiter: Mapped[str] = mapped_column(String(5), nullable=False, default=";")
    encoding: Mapped[str] = mapped_column(String(40), nullable=False, default="utf-8")
    has_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), nullable=True)
    device_kind_id: Mapped[int | None] = mapped_column(ForeignKey("device_kinds.id"), nullable=True)
    import_profile_id: Mapped[int | None] = mapped_column(ForeignKey("import_profiles.id"), nullable=True)
    current_step: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mapping_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_preview_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("ix_import_drafts_updated_at", "updated_at"),
        Index("ix_import_drafts_status", "status"),
        Index("ix_import_drafts_lookup", "manufacturer_id", "device_kind_id"),
    )


class ProductAccessoryLink(Base):
    __tablename__ = "product_accessory_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    accessory_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="csv")
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product = relationship("Product", foreign_keys=[product_id], back_populates="accessory_links")
    accessory_product = relationship("Product", foreign_keys=[accessory_product_id], back_populates="accessory_linked_from")

    __table_args__ = (
        UniqueConstraint("product_id", "accessory_product_id", name="uq_product_accessory_link_pair"),
        Index("ix_product_accessory_link_product", "product_id"),
        Index("ix_product_accessory_link_accessory", "accessory_product_id"),
        Index("ix_product_accessory_link_run", "import_run_id"),
    )


class ProductAccessoryReference(Base):
    __tablename__ = "product_accessory_references"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    raw_value: Mapped[str] = mapped_column(String(260), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(260), nullable=False)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), nullable=True)
    device_kind_id: Mapped[int | None] = mapped_column(ForeignKey("device_kinds.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    matched_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product = relationship("Product", foreign_keys=[product_id], back_populates="accessory_references")
    matched_product = relationship("Product", foreign_keys=[matched_product_id], back_populates="accessory_matched_references")

    __table_args__ = (
        Index("ix_product_accessory_ref_product", "product_id"),
        Index("ix_product_accessory_ref_status", "status"),
        Index("ix_product_accessory_ref_norm", "normalized_value"),
        Index("ix_product_accessory_ref_matched", "matched_product_id"),
        Index("ix_product_accessory_ref_run", "import_run_id"),
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


class SparePartCapture(Base):
    __tablename__ = "spare_part_captures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_spare_part_capture_created_at", "created_at"),
        Index("ix_spare_part_capture_owner_id", "owner_id"),
        Index("ix_spare_part_capture_warehouse_id", "warehouse_id"),
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
    repair_no: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ENTWURF")
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    repair_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    target_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    reservation_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outsmart_row_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    commissioned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commission_account_id: Mapped[int | None] = mapped_column(ForeignKey("email_accounts.id"), nullable=True)
    commission_email_uid: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commission_message_id: Mapped[str | None] = mapped_column(String(400), nullable=True)
    commission_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    repair_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipping_carrier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tracking_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    commission_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    supplier = relationship("Supplier")
    commission_account = relationship("EmailAccount", foreign_keys=[commission_account_id])

    __table_args__ = (
        Index("ix_repair_order_status", "status"),
        Index("ix_repair_orders_article_id", "article_id"),
        Index("ix_repair_orders_supplier_id", "supplier_id"),
        Index("ix_repair_orders_commission_account_id", "commission_account_id"),
    )


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


class RepairEvent(Base):
    __tablename__ = "repair_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repair_order_id: Mapped[int] = mapped_column(ForeignKey("repair_orders.id"), nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_repair_event_order_ts", "repair_order_id", "ts"),
        Index("ix_repair_event_type", "event_type"),
    )


class RepairAttachment(Base):
    __tablename__ = "repair_attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repair_event_id: Mapped[int] = mapped_column(ForeignKey("repair_events.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    paperless_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    outsmart_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_repair_attachment_event", "repair_event_id"),)


class RepairMailLink(Base):
    __tablename__ = "repair_mail_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repair_order_id: Mapped[int] = mapped_column(ForeignKey("repair_orders.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), nullable=False)
    uid: Mapped[str] = mapped_column(String(120), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("account_id", "uid", name="uq_repair_mail_account_uid"),
        Index("ix_repair_mail_order", "repair_order_id"),
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    order_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    po_number: Mapped[str] = mapped_column(String(120), nullable=False)
    order_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=utcnow)
    wanted_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
    )  # draft|sent|confirmed|partially_received|received|closed|cancelled
    condition_set_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_condition_sets.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paperless_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier = relationship("Supplier")

    __table_args__ = (
        UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
        Index("ix_purchase_orders_order_no", "order_no", unique=True),
        Index("ix_purchase_orders_status", "status"),
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    qty_ordered: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    qty_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_product_no: Mapped[str | None] = mapped_column(String(160), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_purchase_order_lines_order", "purchase_order_id"),)


class SupplierConditionSet(Base):
    __tablename__ = "supplier_condition_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agreement_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    brand_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    valid_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skonto_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_term_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skonto_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    basic_discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    basis_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    freight_free_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_order_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bonus_target_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bonus_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    applies_to: Mapped[str] = mapped_column(String(30), nullable=False, default="all")
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), nullable=True)
    device_kind_id: Mapped[int | None] = mapped_column(ForeignKey("device_kinds.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_supplier_condition_sets_supplier", "supplier_id"),
        Index("ix_supplier_condition_sets_active", "active"),
    )


class SupplierConditionProgress(Base):
    __tablename__ = "supplier_condition_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    condition_set_id: Mapped[int] = mapped_column(ForeignKey("supplier_condition_sets.id"), nullable=False)
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    target_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_calculated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("condition_set_id", "period_key", name="uq_supplier_condition_progress_period"),
        Index("ix_supplier_condition_progress_condition", "condition_set_id"),
    )


class SupplierConditionTarget(Base):
    __tablename__ = "supplier_condition_targets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    condition_set_id: Mapped[int] = mapped_column(ForeignKey("supplier_condition_sets.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("condition_set_id", "target_type", name="uq_supplier_condition_target_type"),
        Index("ix_supplier_condition_targets_condition", "condition_set_id"),
    )


class SupplierConditionBonusTier(Base):
    __tablename__ = "supplier_condition_bonus_tiers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    condition_set_id: Mapped[int] = mapped_column(ForeignKey("supplier_condition_sets.id"), nullable=False)
    bonus_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    threshold_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_eur: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_supplier_condition_bonus_tiers_condition", "condition_set_id"),
        Index("ix_supplier_condition_bonus_tiers_kind", "bonus_kind"),
    )


class SupplierConditionFlatBonus(Base):
    __tablename__ = "supplier_condition_flat_bonuses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    condition_set_id: Mapped[int] = mapped_column(ForeignKey("supplier_condition_sets.id"), nullable=False)
    bonus_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    percent_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("condition_set_id", "bonus_kind", name="uq_supplier_condition_flat_bonus_kind"),
        Index("ix_supplier_condition_flat_bonuses_condition", "condition_set_id"),
    )


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    receipt_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    receipt_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=utcnow)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    delivery_note_no: Mapped[str | None] = mapped_column(String(160), nullable=True)
    paperless_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")  # open|posted|closed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("receipt_no", name="uq_goods_receipts_receipt_no"),
        Index("ix_goods_receipts_supplier", "supplier_id"),
        Index("ix_goods_receipts_status", "status"),
    )


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goods_receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"), nullable=False)
    purchase_order_line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_lines.id"), nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty_received: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_cost_received: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_code: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_goods_receipt_lines_receipt", "goods_receipt_id"),
        Index("ix_goods_receipt_lines_po_line", "purchase_order_line_id"),
    )


class PurchaseInvoice(Base):
    __tablename__ = "purchase_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    invoice_no: Mapped[str] = mapped_column(String(160), nullable=False)
    invoice_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=utcnow)
    due_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paperless_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
    )  # draft|matched|approved|booked|paid|disputed
    net_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("supplier_id", "invoice_no", name="uq_purchase_invoice_supplier_invoice"),
        Index("ix_purchase_invoices_status", "status"),
        Index("ix_purchase_invoices_supplier", "supplier_id"),
    )


class PurchaseInvoiceLine(Base):
    __tablename__ = "purchase_invoice_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_invoice_id: Mapped[int] = mapped_column(ForeignKey("purchase_invoices.id"), nullable=False)
    goods_receipt_line_id: Mapped[int | None] = mapped_column(ForeignKey("goods_receipt_lines.id"), nullable=True)
    purchase_order_line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_lines.id"), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_cost_invoiced: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_purchase_invoice_lines_invoice", "purchase_invoice_id"),
        Index("ix_purchase_invoice_lines_gr_line", "goods_receipt_line_id"),
        Index("ix_purchase_invoice_lines_po_line", "purchase_order_line_id"),
    )


class ProductPurchasePrice(Base):
    __tablename__ = "product_purchase_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # order|receipt|invoice|manual
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=utcnow)
    qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_unit_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_product_purchase_prices_product", "product_id"),
        Index("ix_product_purchase_prices_supplier", "supplier_id"),
        Index("ix_product_purchase_prices_effective", "effective_date"),
    )


class AgreementImportDraft(Base):
    __tablename__ = "agreement_import_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    condition_set_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_condition_sets.id"), nullable=True)
    supplier_key: Mapped[str] = mapped_column(String(40), nullable=False, default="seg")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    paperless_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_agreement_import_drafts_supplier", "supplier_id"),
        Index("ix_agreement_import_drafts_status", "status"),
        Index("ix_agreement_import_drafts_paperless", "paperless_document_id"),
    )


class PaperlessLink(Base):
    __tablename__ = "paperless_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    paperless_document_id: Mapped[str] = mapped_column(String(80), nullable=False)
    paperless_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("object_type", "object_id", "paperless_document_id", name="uq_paperless_link_object_document"),
        Index("ix_paperless_links_object", "object_type", "object_id"),
    )


class DocumentInboxItem(Base):
    __tablename__ = "document_inbox_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paperless_document_id: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    correspondent: Mapped[str | None] = mapped_column(String(240), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")  # new|matched|ignored
    suggested_object_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    suggested_object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("paperless_document_id", name="uq_document_inbox_paperless_doc"),
        Index("ix_document_inbox_status", "status"),
    )


class ExternalSyncJob(Base):
    __tablename__ = "external_sync_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_name: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    job_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lock_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    queued_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_external_sync_jobs_system", "system_name"),
        Index("ix_external_sync_jobs_status", "status"),
        Index("ix_external_sync_jobs_job_key", "job_key"),
        Index("ix_external_sync_jobs_lock_key", "lock_key"),
    )


class ExternalLink(Base):
    __tablename__ = "external_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_name: Mapped[str] = mapped_column(String(40), nullable=False)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_key: Mapped[str] = mapped_column(String(160), nullable=False)
    external_row_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    deep_link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("system_name", "object_type", "object_id", name="uq_external_link_object"),
        Index("ix_external_links_external_key", "external_key"),
    )


class Party(Base):
    __tablename__ = "parties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_type: Mapped[str] = mapped_column(String(30), nullable=False, default="company")
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    addresses = relationship("Address", back_populates="party")

    __table_args__ = (
        Index("ix_parties_display_name", "display_name"),
        Index("ix_parties_active", "active"),
    )


class Address(Base):
    __tablename__ = "addresses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    street: Mapped[str | None] = mapped_column(String(240), nullable=True)
    house_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    party = relationship("Party", back_populates="addresses")

    __table_args__ = (
        Index("ix_addresses_party", "party_id"),
        Index("ix_addresses_default", "party_id", "is_default"),
    )


class MasterCustomer(Base):
    __tablename__ = "master_customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False)
    customer_no_internal: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    party = relationship("Party")

    __table_args__ = (
        UniqueConstraint("customer_no_internal", name="uq_master_customers_customer_no_internal"),
        Index("ix_master_customers_party", "party_id"),
        Index("ix_master_customers_status", "status"),
    )


class ServiceLocation(Base):
    __tablename__ = "service_locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    address_id: Mapped[int] = mapped_column(ForeignKey("addresses.id"), nullable=False)
    location_label: Mapped[str] = mapped_column(String(240), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    master_customer = relationship("MasterCustomer")
    party = relationship("Party")
    address = relationship("Address")

    __table_args__ = (
        Index("ix_service_locations_customer", "master_customer_id"),
        Index("ix_service_locations_address", "address_id"),
        Index("ix_service_locations_active", "active"),
    )


class Case(Base):
    __tablename__ = "crm_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_no: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("case_no", name="uq_crm_cases_case_no"),
        Index("ix_crm_cases_status", "status"),
        Index("ix_crm_cases_source_system", "source_system"),
    )


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("crm_cases.id"), nullable=False)
    role_type: Mapped[str] = mapped_column(String(40), nullable=False)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    service_location_id: Mapped[int | None] = mapped_column(ForeignKey("service_locations.id"), nullable=True)
    address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    crm_case = relationship("Case")
    master_customer = relationship("MasterCustomer")
    service_location = relationship("ServiceLocation")
    address = relationship("Address")

    __table_args__ = (
        UniqueConstraint("case_id", "role_type", name="uq_role_assignments_case_role"),
        Index("ix_role_assignments_case", "case_id"),
        Index("ix_role_assignments_customer", "master_customer_id"),
        Index("ix_role_assignments_location", "service_location_id"),
    )


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_customer_id: Mapped[int] = mapped_column(ForeignKey("master_customers.id"), nullable=False)
    system_name: Mapped[str] = mapped_column(String(40), nullable=False)
    external_type: Mapped[str] = mapped_column(String(40), nullable=False)
    external_key: Mapped[str] = mapped_column(String(240), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    master_customer = relationship("MasterCustomer")

    __table_args__ = (
        UniqueConstraint("system_name", "external_type", "external_key", name="uq_external_identities_key"),
        Index("ix_external_identities_customer", "master_customer_id"),
        Index("ix_external_identities_system", "system_name"),
        Index("ix_external_identities_external_id", "external_id"),
    )


class OutsmartRelationStage(Base):
    __tablename__ = "outsmart_relation_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    relation_no: Mapped[str] = mapped_column(String(160), nullable=False)
    debtor_no: Mapped[str | None] = mapped_column(String(160), nullable=True)
    external_row_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(240), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    street: Mapped[str | None] = mapped_column(String(240), nullable=True)
    house_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    name_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    street_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    zip_norm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email_norm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debtor_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_number_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("relation_no", name="uq_outsmart_relation_stage_relation_no"),
        Index("ix_outsmart_relation_stage_debtor_no", "debtor_no"),
        Index("ix_outsmart_relation_stage_external_row_id", "external_row_id"),
        Index("ix_outsmart_relation_stage_debtor_norm", "debtor_norm"),
    )


class OutsmartProjectStage(Base):
    __tablename__ = "outsmart_project_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_code: Mapped[str] = mapped_column(String(160), nullable=False)
    external_row_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    debtor_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    debtor_number_invoice: Mapped[str | None] = mapped_column(String(160), nullable=True)
    name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    start_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    name_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    street_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    zip_norm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email_norm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debtor_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_number_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("project_code", name="uq_outsmart_project_stage_project_code"),
        Index("ix_outsmart_project_stage_debtor_no", "debtor_number"),
        Index("ix_outsmart_project_stage_invoice_debtor_no", "debtor_number_invoice"),
        Index("ix_outsmart_project_stage_debtor_norm", "debtor_norm"),
    )


class OutsmartWorkorderStage(Base):
    __tablename__ = "outsmart_workorder_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workorder_no: Mapped[str] = mapped_column(String(160), nullable=False)
    external_row_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_debtor_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_invoice_debtor_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    customer_name_invoice: Mapped[str | None] = mapped_column(String(240), nullable=True)
    project_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    external_project_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    street: Mapped[str | None] = mapped_column(String(240), nullable=True)
    house_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    street_invoice: Mapped[str | None] = mapped_column(String(240), nullable=True)
    house_no_invoice: Mapped[str | None] = mapped_column(String(40), nullable=True)
    zip_code_invoice: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city_invoice: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    street_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    zip_norm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email_norm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debtor_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_number_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("workorder_no", name="uq_outsmart_workorder_stage_workorder_no"),
        Index("ix_outsmart_workorder_stage_external_row_id", "external_row_id"),
        Index("ix_outsmart_workorder_stage_debtor_no", "customer_debtor_number"),
        Index("ix_outsmart_workorder_stage_invoice_debtor_no", "customer_invoice_debtor_number"),
        Index("ix_outsmart_workorder_stage_debtor_norm", "debtor_norm"),
    )


class SevdeskContactStage(Base):
    __tablename__ = "sevdesk_contact_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sevdesk_contact_id: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    street: Mapped[str | None] = mapped_column(String(240), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parent_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    name_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    street_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    zip_norm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email_norm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debtor_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_number_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("sevdesk_contact_id", name="uq_sevdesk_contact_stage_contact_id"),
        Index("ix_sevdesk_contact_stage_customer_number", "customer_number"),
        Index("ix_sevdesk_contact_stage_customer_number_norm", "customer_number_norm"),
        Index("ix_sevdesk_contact_stage_email_norm", "email_norm"),
    )


class SevdeskContactStatsStage(Base):
    __tablename__ = "sevdesk_contact_stats_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sevdesk_contact_id: Mapped[str] = mapped_column(String(160), nullable=False)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invoice_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_note_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voucher_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("sevdesk_contact_id", name="uq_sevdesk_contact_stats_stage_contact_id"),
        Index("ix_sevdesk_contact_stats_stage_invoice_count", "invoice_count"),
    )


class SevdeskOrderStage(Base):
    __tablename__ = "sevdesk_order_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sevdesk_order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    order_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    order_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    street_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    zip_norm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email_norm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debtor_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_number_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("sevdesk_order_id", name="uq_sevdesk_order_stage_order_id"),
        Index("ix_sevdesk_order_stage_contact_id", "contact_id"),
        Index("ix_sevdesk_order_stage_order_number", "order_number"),
    )


class SevdeskInvoiceStage(Base):
    __tablename__ = "sevdesk_invoice_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sevdesk_invoice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    invoice_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    invoice_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    invoice_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    street_norm: Mapped[str | None] = mapped_column(String(240), nullable=True)
    zip_norm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email_norm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debtor_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_number_norm: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("sevdesk_invoice_id", name="uq_sevdesk_invoice_stage_invoice_id"),
        Index("ix_sevdesk_invoice_stage_contact_id", "contact_id"),
        Index("ix_sevdesk_invoice_stage_invoice_number", "invoice_number"),
    )


class CustomerInitCluster(Base):
    __tablename__ = "customer_init_clusters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(200), nullable=False)
    anchor_system: Mapped[str] = mapped_column(String(40), nullable=False)
    anchor_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conflict_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    master_customer = relationship("MasterCustomer")

    __table_args__ = (
        UniqueConstraint("cluster_key", name="uq_customer_init_clusters_cluster_key"),
        Index("ix_customer_init_clusters_status", "status"),
        Index("ix_customer_init_clusters_master_customer", "master_customer_id"),
    )


class CustomerInitClusterMember(Base):
    __tablename__ = "customer_init_cluster_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("customer_init_clusters.id"), nullable=False)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    stage_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_secondary_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_anchor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cluster = relationship("CustomerInitCluster")

    __table_args__ = (
        UniqueConstraint(
            "cluster_id",
            "source_system",
            "source_type",
            "stage_row_id",
            "external_key",
            name="uq_customer_init_cluster_member_ref",
        ),
        Index("ix_customer_init_cluster_members_cluster", "cluster_id"),
        Index("ix_customer_init_cluster_members_source", "source_system", "source_type"),
    )


class CustomerContactPerson(Base):
    __tablename__ = "customer_contact_persons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_customer_id: Mapped[int] = mapped_column(ForeignKey("master_customers.id"), nullable=False)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False)
    role_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    master_customer = relationship("MasterCustomer")
    party = relationship("Party")

    __table_args__ = (
        Index("ix_customer_contact_persons_customer", "master_customer_id"),
        Index("ix_customer_contact_persons_party", "party_id"),
        Index("ix_customer_contact_persons_active", "active"),
    )


class CustomerObject(Base):
    __tablename__ = "customer_objects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    service_location_id: Mapped[int | None] = mapped_column(ForeignKey("service_locations.id"), nullable=True)
    external_object_code: Mapped[str] = mapped_column(String(160), nullable=False)
    external_row_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    supplier_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    brand_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    type_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    serial_no: Mapped[str | None] = mapped_column(String(160), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    warranty_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    installation_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inspection_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freefields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_parts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    master_customer = relationship("MasterCustomer")
    service_location = relationship("ServiceLocation")

    __table_args__ = (
        UniqueConstraint("external_object_code", name="uq_customer_objects_external_object_code"),
        Index("ix_customer_objects_customer", "master_customer_id"),
        Index("ix_customer_objects_location", "service_location_id"),
        Index("ix_customer_objects_external_row_id", "external_row_id"),
    )


class OutsmartWorkorder(Base):
    __tablename__ = "outsmart_workorders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), nullable=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    service_location_id: Mapped[int | None] = mapped_column(ForeignKey("service_locations.id"), nullable=True)
    customer_object_id: Mapped[int | None] = mapped_column(ForeignKey("customer_objects.id"), nullable=True)
    external_row_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    workorder_no: Mapped[str] = mapped_column(String(160), nullable=False)
    project_external_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scheduled_start: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    employee_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(240), nullable=True)
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_work_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    word_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    forms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    photos_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    materials_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    workperiods_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    workobjects_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    employees_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    crm_case = relationship("Case")
    master_customer = relationship("MasterCustomer")
    service_location = relationship("ServiceLocation")
    customer_object = relationship("CustomerObject")

    __table_args__ = (
        UniqueConstraint("workorder_no", name="uq_outsmart_workorders_workorder_no"),
        Index("ix_outsmart_workorders_case", "case_id"),
        Index("ix_outsmart_workorders_customer", "master_customer_id"),
        Index("ix_outsmart_workorders_external_row_id", "external_row_id"),
        Index("ix_outsmart_workorders_status", "status"),
    )


class CrmTimelineEvent(Base):
    __tablename__ = "crm_timeline_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), nullable=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    service_location_id: Mapped[int | None] = mapped_column(ForeignKey("service_locations.id"), nullable=True)
    customer_object_id: Mapped[int | None] = mapped_column(ForeignKey("customer_objects.id"), nullable=True)
    outsmart_workorder_id: Mapped[int | None] = mapped_column(ForeignKey("outsmart_workorders.id"), nullable=True)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, default="local")
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, default="note")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    crm_case = relationship("Case")
    master_customer = relationship("MasterCustomer")
    service_location = relationship("ServiceLocation")
    customer_object = relationship("CustomerObject")
    outsmart_workorder = relationship("OutsmartWorkorder")

    __table_args__ = (
        Index("ix_crm_timeline_case", "case_id"),
        Index("ix_crm_timeline_customer", "master_customer_id"),
        Index("ix_crm_timeline_workorder", "outsmart_workorder_id"),
        Index("ix_crm_timeline_event_ts", "event_ts"),
    )


class OfferDraft(Base):
    __tablename__ = "offer_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), nullable=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    ordering_party_assignment_id: Mapped[int | None] = mapped_column(ForeignKey("role_assignments.id"), nullable=True)
    service_location_assignment_id: Mapped[int | None] = mapped_column(ForeignKey("role_assignments.id"), nullable=True)
    invoice_recipient_assignment_id: Mapped[int | None] = mapped_column(ForeignKey("role_assignments.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    sevdesk_order_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sevdesk_order_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sevdesk_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pdf_url_local: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    crm_case = relationship("Case")
    master_customer = relationship("MasterCustomer")

    __table_args__ = (
        Index("ix_offer_drafts_case", "case_id"),
        Index("ix_offer_drafts_customer", "master_customer_id"),
        Index("ix_offer_drafts_status", "status"),
        Index("ix_offer_drafts_order_id", "sevdesk_order_id"),
    )


class OfferDraftLine(Base):
    __tablename__ = "offer_draft_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_draft_id: Mapped[int] = mapped_column(ForeignKey("offer_drafts.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    unit: Mapped[str] = mapped_column(String(40), nullable=False, default="Stk")
    unit_price_net: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.19)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    offer_draft = relationship("OfferDraft")
    product = relationship("Product")

    __table_args__ = (
        Index("ix_offer_draft_lines_offer", "offer_draft_id"),
        Index("ix_offer_draft_lines_product", "product_id"),
    )


class InvoiceDraft(Base):
    __tablename__ = "invoice_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("crm_cases.id"), nullable=True)
    master_customer_id: Mapped[int | None] = mapped_column(ForeignKey("master_customers.id"), nullable=True)
    invoice_recipient_assignment_id: Mapped[int | None] = mapped_column(ForeignKey("role_assignments.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    offer_draft_id: Mapped[int | None] = mapped_column(ForeignKey("offer_drafts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    sevdesk_invoice_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sevdesk_invoice_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sevdesk_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pdf_url_local: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    invoice_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    crm_case = relationship("Case")
    master_customer = relationship("MasterCustomer")
    offer_draft = relationship("OfferDraft")

    __table_args__ = (
        Index("ix_invoice_drafts_case", "case_id"),
        Index("ix_invoice_drafts_customer", "master_customer_id"),
        Index("ix_invoice_drafts_status", "status"),
        Index("ix_invoice_drafts_invoice_id", "sevdesk_invoice_id"),
    )


class InvoiceDraftLine(Base):
    __tablename__ = "invoice_draft_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_draft_id: Mapped[int] = mapped_column(ForeignKey("invoice_drafts.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    unit: Mapped[str] = mapped_column(String(40), nullable=False, default="Stk")
    unit_price_net: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.19)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    invoice_draft = relationship("InvoiceDraft")
    product = relationship("Product")

    __table_args__ = (
        Index("ix_invoice_draft_lines_invoice", "invoice_draft_id"),
        Index("ix_invoice_draft_lines_product", "product_id"),
    )


class IncomingVoucherDraft(Base):
    __tablename__ = "incoming_voucher_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    purchase_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_invoices.id"), nullable=True)
    linked_document_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    paperless_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    goods_receipt_id: Mapped[int | None] = mapped_column(ForeignKey("goods_receipts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    sevdesk_voucher_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sevdesk_voucher_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    voucher_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    net_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    supplier = relationship("Supplier")
    purchase_invoice = relationship("PurchaseInvoice")
    purchase_order = relationship("PurchaseOrder")
    goods_receipt = relationship("GoodsReceipt")

    __table_args__ = (
        Index("ix_incoming_voucher_drafts_supplier", "supplier_id"),
        Index("ix_incoming_voucher_drafts_invoice", "purchase_invoice_id"),
        Index("ix_incoming_voucher_drafts_status", "status"),
        Index("ix_incoming_voucher_drafts_voucher_id", "sevdesk_voucher_id"),
    )


class IncomingVoucherDraftLine(Base):
    __tablename__ = "incoming_voucher_draft_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incoming_voucher_draft_id: Mapped[int] = mapped_column(ForeignKey("incoming_voucher_drafts.id"), nullable=False)
    account_datev_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tax_rule_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.19)
    sum_net: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sum_gross: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_center_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    incoming_voucher_draft = relationship("IncomingVoucherDraft")

    __table_args__ = (
        Index("ix_incoming_voucher_draft_lines_voucher", "incoming_voucher_draft_id"),
    )


class DunningCase(Base):
    __tablename__ = "dunning_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_draft_id: Mapped[int | None] = mapped_column(ForeignKey("invoice_drafts.id"), nullable=True)
    sevdesk_invoice_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("master_customers.id"), nullable=False)
    current_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    due_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_due: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    next_action_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_contact_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    invoice_draft = relationship("InvoiceDraft")
    customer = relationship("MasterCustomer")

    __table_args__ = (
        UniqueConstraint("invoice_draft_id", name="uq_dunning_cases_invoice_draft"),
        Index("ix_dunning_cases_customer", "customer_id"),
        Index("ix_dunning_cases_status", "status"),
        Index("ix_dunning_cases_next_action", "next_action_at"),
    )


class DunningAction(Base):
    __tablename__ = "dunning_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dunning_case_id: Mapped[int] = mapped_column(ForeignKey("dunning_cases.id"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False, default="note")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    mail_outbox_id: Mapped[int | None] = mapped_column(ForeignKey("email_outbox.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dunning_case = relationship("DunningCase")
    mail_outbox = relationship("EmailOutbox")

    __table_args__ = (
        Index("ix_dunning_actions_case", "dunning_case_id"),
        Index("ix_dunning_actions_type", "action_type"),
        Index("ix_dunning_actions_created", "created_at"),
    )


class AiPromptDefinition(Base):
    __tablename__ = "ai_prompt_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_schema_name: Mapped[str] = mapped_column(String(80), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("task_name", "version", name="uq_ai_prompt_definitions_task_version"),
        Index("ix_ai_prompt_definitions_task", "task_name"),
        Index("ix_ai_prompt_definitions_active", "active"),
    )


class AiDecisionLog(Base):
    __tablename__ = "ai_decision_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False, default="local-heuristic")
    risk_class: Mapped[str] = mapped_column(String(20), nullable=False, default="gruen")
    input_refs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="suggested")
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    override_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_object_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    approved_by = relationship("User")

    __table_args__ = (
        Index("ix_ai_decision_logs_task", "task_name"),
        Index("ix_ai_decision_logs_status", "status"),
        Index("ix_ai_decision_logs_object", "related_object_type", "related_object_id"),
        Index("ix_ai_decision_logs_created", "created_at"),
    )


class AiReviewQueueItem(Base):
    __tablename__ = "ai_review_queue_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ai_decision_log_id: Mapped[int] = mapped_column(ForeignKey("ai_decision_logs.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="mittel")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ai_decision_log = relationship("AiDecisionLog")

    __table_args__ = (
        Index("ix_ai_review_queue_status", "status"),
        Index("ix_ai_review_queue_priority", "priority"),
        Index("ix_ai_review_queue_object", "object_type", "object_id"),
    )


class SupervisorFinding(Base):
    __tablename__ = "supervisor_findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="mittel")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_object_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_decision_log_id: Mapped[int | None] = mapped_column(ForeignKey("ai_decision_logs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ai_decision_log = relationship("AiDecisionLog")

    __table_args__ = (
        Index("ix_supervisor_findings_type", "finding_type"),
        Index("ix_supervisor_findings_status", "status"),
        Index("ix_supervisor_findings_severity", "severity"),
        Index("ix_supervisor_findings_object", "related_object_type", "related_object_id"),
    )


class ProcedureGuidelineSection(Base):
    __tablename__ = "procedure_guideline_sections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    updated_by = relationship("User")

    __table_args__ = (
        UniqueConstraint("section_key", "version", name="uq_procedure_guideline_section_version"),
        Index("ix_procedure_guideline_sections_key", "section_key"),
        Index("ix_procedure_guideline_sections_active", "active"),
    )


class AiEvalCase(Base):
    __tablename__ = "ai_eval_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(80), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    expected_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ai_eval_cases_task", "task_name"),
        Index("ix_ai_eval_cases_active", "active"),
    )


class AiEvalRun(Base):
    __tablename__ = "ai_eval_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_ai_eval_runs_task", "task_name"),
        Index("ix_ai_eval_runs_started", "started_at"),
    )


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
