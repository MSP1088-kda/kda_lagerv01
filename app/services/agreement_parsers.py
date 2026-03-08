from __future__ import annotations

import re
from typing import Callable


_AMOUNT_TOKEN_RE = re.compile(r"(?:EUR|EURO|TEUR|T€|TSD\.?\s*€|TSD\.?|€)?\s*[-+]?\d[\d\s.,]*\s*(?:EUR|EURO|TEUR|T€|TSD\.?\s*€|TSD\.?|€)?", re.IGNORECASE)
_PERCENT_RE = re.compile(r"([-+]?\d{1,2}(?:[.,]\d{1,2})?)\s*%")
_DATE_RE = re.compile(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})")


def _clean_text(raw: str | None) -> str:
    text = str(raw or "")
    text = text.replace("\xa0", " ").replace("\u200b", " ")
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        compact = re.sub(r"\s+", " ", line).strip(" \t;|")
        if compact:
            cleaned_lines.append(compact)
    return "\n".join(cleaned_lines).strip()


def _compact_text(raw: str | None) -> str:
    return re.sub(r"\s+", " ", _clean_text(raw)).strip()


def _snippet(text: str, start: int, end: int, radius: int = 80) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].strip()


def _to_float(raw: str | None) -> float | None:
    token = str(raw or "").strip()
    if not token:
        return None
    token = token.replace(" ", "")
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        token = token.replace(".", "").replace(",", ".")
    try:
        return float(token)
    except Exception:
        return None


def _amount_to_cents(raw: str | None) -> int | None:
    token = str(raw or "").strip()
    if not token:
        return None
    upper = token.upper()
    factor = 1.0
    if "TEUR" in upper or "T€" in upper or "TSD" in upper:
        factor = 1000.0
    number_token = re.sub(r"[^0-9,.-]", "", token)
    value = _to_float(number_token)
    if value is None:
        return None
    if factor == 1.0 and abs(value) >= 100000 and "," not in number_token and "." not in number_token:
        return int(round(value * 100))
    return int(round(value * factor * 100))


def _parse_date_token(token: str | None) -> str | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    parts = re.split(r"[./-]", raw)
    if len(parts) != 3:
        return None
    day, month, year = parts
    if len(year) == 2:
        year = f"20{year}"
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except Exception:
        return None


def _find_regex(text: str, patterns: list[str]) -> tuple[str | None, str | None]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = str(match.group(1) or "").strip() or None
        if value:
            return value, _snippet(text, match.start(1), match.end(1))
    return None, None


def _extract_date_range(text: str) -> tuple[str | None, str | None, str | None]:
    patterns = [
        r"g[üu]ltig\s*(?:vom|ab)?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*(?:bis|\-|–|—)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"laufzeit\s*(?:vom|ab)?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*(?:bis|\-|–|—)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        return (
            _parse_date_token(match.group(1)),
            _parse_date_token(match.group(2)),
            _snippet(text, match.start(), match.end()),
        )
    dates = list(_DATE_RE.finditer(text))
    if len(dates) >= 2:
        return (
            _parse_date_token(dates[0].group(1)),
            _parse_date_token(dates[1].group(1)),
            _snippet(text, dates[0].start(), dates[1].end()),
        )
    return None, None, None


def _extract_target_table(text: str) -> tuple[dict[str, int | None], str | None]:
    lower = text.lower()
    start = lower.find("umsatzziele")
    if start < 0:
        return {}, None
    end = len(text)
    for stop in ("\n    3. rabatte", "\n3. rabatte", "\n3. Rabatte", "\n 3. Rabatte"):
        pos = text.find(stop, start + 1)
        if pos > start and pos < end:
            end = pos
    block = text[start:end].strip()
    target_line = ""
    for line in block.split("\n"):
        compact = " ".join(line.split()).strip()
        if re.search(r"\bziel\b.*\b20\d{2}\b", compact, flags=re.IGNORECASE):
            target_line = compact
            break
    if not target_line:
        return {}, block[:240] if block else None
    values = [
        token
        for token in re.findall(r"\d+(?:[.,]\d+)?", target_line)
        if not re.fullmatch(r"20\d{2}", token)
    ]
    if len(values) < 3:
        return {}, block[:240] if block else None
    return (
        {
            "solo": _amount_to_cents(f"{values[0]} TEUR"),
            "einbau": _amount_to_cents(f"{values[1]} TEUR"),
            "gesamt": _amount_to_cents(f"{values[-1]} TEUR"),
        },
        block[:240] if block else None,
    )


def _extract_amount_near(text: str, labels: tuple[str, ...]) -> tuple[int | None, str | None]:
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        low = line.lower()
        if not any(label in low for label in labels):
            continue
        block = " ".join(lines[idx : idx + 2]).strip()
        match = None
        for candidate in _AMOUNT_TOKEN_RE.finditer(block):
            cents = _amount_to_cents(candidate.group(0))
            if cents is None:
                continue
            match = (cents, candidate)
            break
        if match:
            return match[0], block[:220]
    compact = _compact_text(text)
    for label in labels:
        pattern = rf"{label}[^\d]{{0,40}}({_AMOUNT_TOKEN_RE.pattern})"
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            continue
        cents = _amount_to_cents(match.group(1))
        if cents is not None:
            return cents, _snippet(compact, match.start(1), match.end(1))
    return None, None


def _extract_percent_near(text: str, labels: tuple[str, ...]) -> tuple[float | None, str | None]:
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        low = line.lower()
        if not any(label in low for label in labels):
            continue
        block = " ".join(lines[idx : idx + 2]).strip()
        match = _PERCENT_RE.search(block)
        if match:
            value = _to_float(match.group(1))
            if value is not None:
                return value, block[:220]
    compact = _compact_text(text)
    for label in labels:
        match = re.search(rf"{label}.{{0,80}}?([-+]?\d{{1,2}}(?:[.,]\d{{1,2}})?)\s*%", compact, flags=re.IGNORECASE)
        if match:
            value = _to_float(match.group(1))
            if value is not None:
                return value, _snippet(compact, match.start(1), match.end(1))
    return None, None


def _extract_payment_terms(text: str) -> tuple[dict[str, int | float | None], dict[str, str]]:
    out: dict[str, int | float | None] = {"skonto_days": None, "skonto_percent": None, "net_days": None}
    snippets: dict[str, str] = {}
    compact = _compact_text(text)
    line_match = re.search(
        r"(\d{1,3})\s*tage?\s*([-+]?\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*(\d{1,3})\s*tage?\s*netto",
        compact,
        flags=re.IGNORECASE,
    )
    if line_match:
        skonto_days = _to_float(line_match.group(1))
        skonto_percent = _to_float(line_match.group(2))
        net_days = _to_float(line_match.group(3))
        if skonto_days is not None and skonto_percent is not None and net_days is not None:
            out["skonto_days"] = int(round(skonto_days))
            out["skonto_percent"] = skonto_percent
            out["net_days"] = int(round(net_days))
            snippets["payment_terms"] = _snippet(compact, line_match.start(), line_match.end())
            return out, snippets
    patterns = [
        r"(\d{1,3})\s*tage?\s*([-+]?\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*skonto",
        r"([-+]?\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*skonto\s*(?:bei|innerhalb\s+von)?\s*(\d{1,3})\s*tage?",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            continue
        first = _to_float(match.group(1))
        second = _to_float(match.group(2))
        if first is not None and second is not None:
            if "%" in match.group(0).split()[0]:
                out["skonto_percent"] = first
                out["skonto_days"] = int(round(second))
            else:
                out["skonto_days"] = int(round(first))
                out["skonto_percent"] = second
            snippets["payment_terms"] = _snippet(compact, match.start(), match.end())
            break
    net_match = re.search(r"(\d{1,3})\s*tage?\s*netto", compact, flags=re.IGNORECASE)
    if net_match:
        value = _to_float(net_match.group(1))
        if value is not None:
            out["net_days"] = int(round(value))
            snippets.setdefault("payment_terms", _snippet(compact, net_match.start(), net_match.end()))
    return out, snippets


def _extract_basis_label(text: str, snippet_hint: str | None = None) -> str | None:
    search = " ".join(part for part in (snippet_hint, _compact_text(text)) if part)
    match = re.search(r"\b(HLP|UVP|NLP|EK|LISTENPREIS)\b", search, flags=re.IGNORECASE)
    if not match:
        return None
    return str(match.group(1) or "").upper()


def _extract_block(text: str, headings: tuple[str, ...], stop_headings: tuple[str, ...]) -> str:
    lower = text.lower()
    start = -1
    for heading in headings:
        pos = lower.find(heading)
        if pos >= 0 and (start < 0 or pos < start):
            start = pos
    if start < 0:
        return ""
    end = len(text)
    for stop in stop_headings:
        pos = lower.find(stop, start + 1)
        if pos > start and pos < end:
            end = pos
    return text[start:end].strip()


def _extract_tiers(block: str, *, expect_percent: bool, expect_amount: bool) -> list[dict[str, int | float | None]]:
    rows: list[dict[str, int | float | None]] = []
    seen: set[tuple[int | None, float | None, int | None]] = set()
    if not block:
        return rows
    for line in block.split("\n"):
        amounts = [_amount_to_cents(match.group(0)) for match in _AMOUNT_TOKEN_RE.finditer(line)]
        amounts = [item for item in amounts if item is not None]
        percents = [_to_float(match.group(1)) for match in _PERCENT_RE.finditer(line)]
        percents = [item for item in percents if item is not None]
        threshold = amounts[0] if amounts else None
        percent_value = percents[0] if expect_percent and percents else None
        amount_eur = amounts[1] if expect_amount and len(amounts) > 1 else None
        if expect_amount and amount_eur is None and len(amounts) == 1 and not percents:
            amount_eur = amounts[0]
            threshold = None
        key = (threshold, percent_value, amount_eur)
        if threshold is None and percent_value is None and amount_eur is None:
            continue
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "threshold": threshold,
                "percent": percent_value,
                "amount_eur": amount_eur,
            }
        )
    return rows


class SEGAnnualAgreementParser:
    supplier_key = "seg"
    supplier_name = "SEG Hausgeräte GmbH"

    @classmethod
    def parse(cls, raw_text: str | None, metadata: dict | None = None) -> dict:
        text = _clean_text(raw_text)
        compact = _compact_text(text)
        source_snippets: dict[str, str] = {}
        parser_notes: list[str] = []
        metadata = metadata or {}

        contains_seg = "seg" in compact.lower() or "hausger" in compact.lower()
        contains_siemens = "siemens" in compact.lower()
        unsupported_document = not (contains_seg or contains_siemens)
        if unsupported_document:
            parser_notes.append("Dokument wirkt nicht wie eine SEG-/Siemens-Jahresvereinbarung.")

        brand = "Siemens"
        if contains_siemens:
            match = re.search(r"\bsiemens\b", compact, flags=re.IGNORECASE)
            if match:
                source_snippets["brand"] = _snippet(compact, match.start(), match.end())
        else:
            parser_notes.append("Marke Siemens wurde nicht klar erkannt und als Vorschlag vorbelegt.")

        customer_no, snippet = _find_regex(
            text,
            [
                r"kunden(?:nummer|nr\.?|[- ]?nr\.?)[^A-Za-z0-9]{0,8}([A-Za-z0-9\-/]{4,})",
                r"kd\.?[- ]?nr\.?[^A-Za-z0-9]{0,8}([A-Za-z0-9\-/]{4,})",
            ],
        )
        if snippet:
            source_snippets["customer_no"] = snippet

        agreement_version, snippet = _find_regex(
            text,
            [
                r"jv\s*/\s*version[^A-Za-z0-9]{0,8}([A-Za-z0-9][A-Za-z0-9\-/.]{2,})",
                r"vereinbarungs?(?:nummer|nr\.?|[- ]?nr\.?)[^A-Za-z0-9]{0,8}([A-Za-z0-9][A-Za-z0-9\-/.]{2,})",
                r"versions?(?:nummer|nr\.?|[- ]?nr\.?)[^A-Za-z0-9]{0,8}([A-Za-z0-9][A-Za-z0-9\-/.]{2,})",
                r"vertrags?(?:nummer|nr\.?|[- ]?nr\.?)[^A-Za-z0-9]{0,8}([A-Za-z0-9][A-Za-z0-9\-/.]{2,})",
            ],
        )
        if snippet:
            source_snippets["agreement_version"] = snippet

        valid_from, valid_to, snippet = _extract_date_range(text)
        if snippet:
            source_snippets["validity"] = snippet

        table_targets, table_snippet = _extract_target_table(text)
        solo = table_targets.get("solo")
        einbau = table_targets.get("einbau")
        gesamt = table_targets.get("gesamt")
        if table_snippet:
            if solo is not None:
                source_snippets["targets.solo"] = table_snippet
            if einbau is not None:
                source_snippets["targets.einbau"] = table_snippet
            if gesamt is not None:
                source_snippets["targets.gesamt"] = table_snippet
        if solo is None:
            solo, snippet = _extract_amount_near(text, ("solo", "solo-umsatz", "zielumsatz solo"))
            if snippet:
                source_snippets["targets.solo"] = snippet
        if einbau is None:
            einbau, snippet = _extract_amount_near(text, ("einbau", "einbauumsatz", "zielumsatz einbau"))
            if snippet:
                source_snippets["targets.einbau"] = snippet
        if gesamt is None:
            gesamt, snippet = _extract_amount_near(text, ("gesamt", "gesamtumsatz", "zielumsatz gesamt"))
            if snippet:
                source_snippets["targets.gesamt"] = snippet

        base_percent, snippet = _extract_percent_near(text, ("grundrabatt", "basisrabatt", "warenrabatt"))
        basis_label = _extract_basis_label(text, snippet)
        if snippet:
            source_snippets["discount.base_percent"] = snippet
        if basis_label:
            source_snippets.setdefault("discount.basis_label", snippet or basis_label)

        payment_terms, payment_snippets = _extract_payment_terms(text)
        source_snippets.update(payment_snippets)

        concentration_bonus_percent, snippet = _extract_percent_near(text, ("konzentrationsbonus",))
        if snippet:
            source_snippets["bonuses.concentration_bonus_percent"] = snippet

        annual_block = _extract_block(
            text,
            ("jahresbonus",),
            ("erfüllungsbonus", "erfuellungsbonus", "erfullungsbonus", "staffelbonus", "konzentrationsbonus", "zahlungsbeding", "grundrabatt"),
        )
        annual_bonus_tiers = _extract_tiers(annual_block, expect_percent=True, expect_amount=False)
        if annual_block:
            source_snippets["bonuses.annual_bonus_tiers"] = annual_block[:240]

        achievement_block = _extract_block(
            text,
            ("erfüllungsbonus", "erfuellungsbonus", "erfullungsbonus"),
            ("staffelbonus", "konzentrationsbonus", "zahlungsbeding", "grundrabatt"),
        )
        achievement_bonus_tiers = _extract_tiers(achievement_block, expect_percent=False, expect_amount=True)
        if achievement_block:
            source_snippets["bonuses.achievement_bonus_tiers"] = achievement_block[:240]

        tier_block = _extract_block(text, ("staffelbonus",), ("konzentrationsbonus", "zahlungsbeding", "grundrabatt"))
        tier_bonus_tiers = _extract_tiers(tier_block, expect_percent=True, expect_amount=False)
        if tier_block:
            source_snippets["bonuses.tier_bonus_tiers"] = tier_block[:240]

        required_checks: list[tuple[str, bool]] = [
            ("Kundennummer", bool(customer_no)),
            ("Gültig von", bool(valid_from)),
            ("Gültig bis", bool(valid_to)),
            ("Grundrabatt", base_percent is not None),
            ("Netto-Tage", payment_terms.get("net_days") is not None),
            ("Skonto", payment_terms.get("skonto_percent") is not None),
        ]
        required_checks.extend(
            [
                ("Zielumsatz Solo", solo is not None),
                ("Zielumsatz Einbau", einbau is not None),
                ("Zielumsatz Gesamt", gesamt is not None),
            ]
        )
        for label, present in required_checks:
            if not present:
                parser_notes.append(f"{label} konnte nicht sicher erkannt werden.")

        found_required = sum(1 for _, present in required_checks if present)
        confidence = 0.18 + (found_required / max(1, len(required_checks))) * 0.72
        if agreement_version:
            confidence += 0.04
        if annual_bonus_tiers or achievement_bonus_tiers or tier_bonus_tiers:
            confidence += 0.03
        if unsupported_document:
            confidence -= 0.35
        confidence = max(0.05, min(0.99, confidence))

        return {
            "supplier_name": cls.supplier_name,
            "supplier_key": cls.supplier_key,
            "brand": brand,
            "customer_no": customer_no,
            "agreement_version": agreement_version,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "targets": {
                "solo": solo,
                "einbau": einbau,
                "gesamt": gesamt,
            },
            "discount": {
                "base_percent": base_percent,
                "basis_label": basis_label,
            },
            "payment_terms": {
                "skonto_days": payment_terms.get("skonto_days"),
                "skonto_percent": payment_terms.get("skonto_percent"),
                "net_days": payment_terms.get("net_days"),
            },
            "bonuses": {
                "concentration_bonus_percent": concentration_bonus_percent,
                "annual_bonus_tiers": annual_bonus_tiers,
                "achievement_bonus_tiers": achievement_bonus_tiers,
                "tier_bonus_tiers": tier_bonus_tiers,
            },
            "parser_notes": parser_notes,
            "parser_confidence": round(confidence, 2),
            "source_snippets": source_snippets,
            "unsupported_document": unsupported_document,
            "source_hint": str(metadata.get("source_filename") or metadata.get("paperless_document_id") or "").strip() or None,
        }


PARSER_REGISTRY: dict[str, Callable[..., dict]] = {
    "seg": SEGAnnualAgreementParser,
}
