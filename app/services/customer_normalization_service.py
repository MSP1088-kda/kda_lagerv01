from __future__ import annotations

import re
import unicodedata

_COMPANY_SUFFIXES = (
    "gmbh",
    "mbh",
    "ug",
    "ug haftungsbeschraenkt",
    "ag",
    "kg",
    "ohg",
    "ek",
    "e.k",
    "e k",
    "gbr",
    "e.v",
    "ev",
    "ltd",
)


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _ascii_fold(value: str | None) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = text.replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_text(value: str | None) -> str:
    text = _ascii_fold(value).lower()
    text = re.sub(r"[\(\)\[\]\{\},;]", " ", text)
    text = re.sub(r"[^a-z0-9+\-/ ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_name(value: str | None) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    parts = [part for part in text.split(" ") if part]
    while parts and parts[-1].strip(".") in _COMPANY_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def normalize_street(value: str | None) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    replacements = {
        "str.": "strasse",
        "str ": "strasse ",
        "strassee": "strasse",
        "straße": "strasse",
        "pl.": "platz",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def normalize_zip(value: str | None) -> str:
    return re.sub(r"[^0-9a-zA-Z]", "", str(value or "").strip())


def normalize_email(value: str | None) -> str:
    return normalize_text(value).replace(" ", "")


def normalize_phone(value: str | None) -> str:
    raw = re.sub(r"[^0-9+]", "", str(value or "").strip())
    if raw.startswith("00"):
        raw = f"+{raw[2:]}"
    if raw.startswith("+"):
        return "+" + re.sub(r"[^0-9]", "", raw[1:])
    return re.sub(r"[^0-9]", "", raw)


def normalize_identifier(value: str | None) -> str:
    return re.sub(r"[^0-9a-zA-Z]", "", _ascii_fold(value).lower())


def stage_normalized_fields(
    *,
    name: str | None = None,
    street: str | None = None,
    zip_code: str | None = None,
    city: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    debtor: str | None = None,
    customer_number: str | None = None,
) -> dict[str, str | None]:
    return {
        "name_norm": normalize_name(name) or None,
        "street_norm": normalize_street(street) or None,
        "zip_norm": normalize_zip(zip_code) or None,
        "city_norm": normalize_text(city) or None,
        "email_norm": normalize_email(email) or None,
        "phone_norm": normalize_phone(phone) or None,
        "debtor_norm": normalize_identifier(debtor) or None,
        "customer_number_norm": normalize_identifier(customer_number) or None,
    }
