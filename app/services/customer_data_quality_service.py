from __future__ import annotations

import difflib
import json
import re
import smtplib
import socket
from urllib import error as url_error, request as url_request
from urllib.parse import urlencode


COMMON_EMAIL_DOMAINS = [
    "gmail.com",
    "googlemail.com",
    "gmx.de",
    "gmx.net",
    "web.de",
    "outlook.com",
    "hotmail.com",
    "hotmail.de",
    "live.com",
    "live.de",
    "icloud.com",
    "me.com",
    "mac.com",
    "yahoo.com",
    "yahoo.de",
    "t-online.de",
    "freenet.de",
    "aol.com",
    "aol.de",
    "proton.me",
    "protonmail.com",
]

COMMON_EMAIL_DOMAIN_CORRECTIONS = {
    "gmai.com": "gmail.com",
    "gmial.com": "gmail.com",
    "gmail.con": "gmail.com",
    "gmail.co": "gmail.com",
    "googlemai.com": "googlemail.com",
    "outllok.com": "outlook.com",
    "outlok.com": "outlook.com",
    "hotmai.com": "hotmail.com",
    "hotnail.com": "hotmail.com",
    "icloud.co": "icloud.com",
    "icloud.con": "icloud.com",
    "yaho.com": "yahoo.com",
    "yahho.com": "yahoo.com",
    "webd.de": "web.de",
    "we.de": "web.de",
    "gmx,net": "gmx.net",
    "gmx,de": "gmx.de",
    "gmx.dee": "gmx.de",
    "gmx.ne": "gmx.net",
    "t-onine.de": "t-online.de",
    "tonline.de": "t-online.de",
}

EMAIL_REGEX = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+$", re.IGNORECASE)
IBAN_REGEX = re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){10,30}\b")
BIC_REGEX = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")

ADDRESS_USER_AGENT = "kda-customer-quality/1.0"
ADDRESS_URL = "https://nominatim.openstreetmap.org/search"
DNS_JSON_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)


def _clean_text(value: object | None) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).strip()


def _normalize_key(value: object | None) -> str:
    text = _clean_text(value).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_domain(value: str | None) -> str:
    return _clean_text(value).lower().strip(".")


def normalize_iban(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def iban_is_valid(value: str | None) -> bool:
    iban = normalize_iban(value)
    if len(iban) < 15 or len(iban) > 34:
        return False
    try:
        rearranged = iban[4:] + iban[:4]
        expanded = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
        return int(expanded) % 97 == 1
    except Exception:
        return False


def _looks_like_bank_document(*parts: str | None) -> bool:
    haystack = " ".join(_clean_text(part).lower() for part in parts if _clean_text(part))
    keywords = (
        "kontoauszug",
        "bankauszug",
        "umsatzanzeige",
        "zahlungseingang",
        "ueberweisung",
        "gutschrift",
        "sepa",
        "zahlungsavis",
        "transaktion",
        "kontobewegung",
    )
    return any(keyword in haystack for keyword in keywords)


def _extract_holder(window: str, customer_name: str | None = None) -> str:
    patterns = (
        r"kontoinhaber\s*[:\-]?\s*([^\n,;]{3,120})",
        r"auftraggeber\s*[:\-]?\s*([^\n,;]{3,120})",
        r"zahlungspflichtiger\s*[:\-]?\s*([^\n,;]{3,120})",
        r"zahler\s*[:\-]?\s*([^\n,;]{3,120})",
        r"debitor\s*[:\-]?\s*([^\n,;]{3,120})",
        r"kunde\s*[:\-]?\s*([^\n,;]{3,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, window, flags=re.IGNORECASE)
        if match:
            holder = _clean_text(match.group(1))
            if holder:
                return holder
    customer_label = _clean_text(customer_name)
    if customer_label and _normalize_key(customer_label) in _normalize_key(window):
        return customer_label
    return ""


def _extract_bank_name(window: str) -> str:
    patterns = (
        r"bank\s*[:\-]?\s*([^\n,;]{3,120})",
        r"kreditinstitut\s*[:\-]?\s*([^\n,;]{3,120})",
        r"institut\s*[:\-]?\s*([^\n,;]{3,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, window, flags=re.IGNORECASE)
        if match:
            bank_name = _clean_text(match.group(1))
            if bank_name:
                return bank_name
    return ""


def extract_bank_candidates_from_text(
    text: str | None,
    *,
    title: str | None = None,
    correspondent: str | None = None,
    document_type: str | None = None,
    customer_name: str | None = None,
) -> list[dict[str, object]]:
    raw_text = str(text or "")
    if not raw_text:
        return []
    if not _looks_like_bank_document(title, correspondent, document_type, raw_text) and "iban" not in raw_text.lower():
        return []
    bic_matches = [match.group(0) for match in BIC_REGEX.finditer(raw_text.upper())]
    candidates: list[dict[str, object]] = []
    customer_key = _normalize_key(customer_name)
    for match in IBAN_REGEX.finditer(raw_text.upper()):
        iban_raw = match.group(0)
        iban = normalize_iban(iban_raw)
        if not iban_is_valid(iban):
            continue
        window_start = max(0, match.start() - 260)
        window_end = min(len(raw_text), match.end() + 260)
        window = raw_text[window_start:window_end]
        holder = _extract_holder(window, customer_name)
        bank_name = _extract_bank_name(window)
        bic = ""
        for bic_candidate in bic_matches:
            if bic_candidate in window.upper():
                bic = bic_candidate
                break
        confidence = 1
        if _looks_like_bank_document(title, correspondent, document_type):
            confidence += 3
        if customer_key and customer_key in _normalize_key(window):
            confidence += 4
        if any(token in window.lower() for token in ("auftraggeber", "zahlungspflichtiger", "zahler", "kontoinhaber")):
            confidence += 2
        if holder and customer_key and customer_key in _normalize_key(holder):
            confidence += 2
        candidates.append(
            {
                "iban": iban,
                "bic": bic,
                "account_holder": holder,
                "bank_name": bank_name,
                "confidence": confidence,
                "context": _clean_text(window)[:240],
            }
        )
    return candidates


def pick_best_bank_candidate(candidates: list[dict[str, object]]) -> dict[str, object]:
    grouped: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        iban = normalize_iban(str(candidate.get("iban") or ""))
        if not iban:
            continue
        group = grouped.setdefault(
            iban,
            {
                "iban": iban,
                "bic": "",
                "account_holder": "",
                "bank_name": "",
                "confidence": 0,
                "count": 0,
                "contexts": [],
                "source_document_ids": [],
            },
        )
        group["count"] = int(group.get("count") or 0) + 1
        group["confidence"] = int(group.get("confidence") or 0) + int(candidate.get("confidence") or 0)
        if not group.get("bic") and _clean_text(candidate.get("bic")):
            group["bic"] = _clean_text(candidate.get("bic"))
        if not group.get("account_holder") and _clean_text(candidate.get("account_holder")):
            group["account_holder"] = _clean_text(candidate.get("account_holder"))
        if not group.get("bank_name") and _clean_text(candidate.get("bank_name")):
            group["bank_name"] = _clean_text(candidate.get("bank_name"))
        context = _clean_text(candidate.get("context"))
        if context:
            contexts = group["contexts"]
            if isinstance(contexts, list) and context not in contexts:
                contexts.append(context)
        source_document_id = _clean_text(candidate.get("source_document_id"))
        if source_document_id:
            source_ids = group["source_document_ids"]
            if isinstance(source_ids, list) and source_document_id not in source_ids:
                source_ids.append(source_document_id)
    best: dict[str, object] = {}
    best_score = -1
    for group in grouped.values():
        score = int(group.get("confidence") or 0) + (max(0, int(group.get("count") or 0) - 1) * 2)
        if score > best_score:
            best_score = score
            best = dict(group)
            best["confidence"] = score
    return best


def _zip_pattern(country_code: str) -> str | None:
    code = _clean_text(country_code).upper()
    if code == "DE":
        return r"^\d{5}$"
    if code in {"AT", "CH"}:
        return r"^\d{4}$"
    return None


def _address_local_validation(street: str, house_no: str, zip_code: str, city: str, country_code: str) -> dict[str, object]:
    pattern = _zip_pattern(country_code)
    if pattern and zip_code and not re.match(pattern, zip_code):
        return {
            "status": "invalid",
            "message": "PLZ-Format passt nicht zum Land.",
            "source": "local",
        }
    if street and not any(ch.isalpha() for ch in street):
        return {
            "status": "invalid",
            "message": "Die Strasse wirkt unvollstaendig.",
            "source": "local",
        }
    if zip_code and not city:
        return {
            "status": "partial",
            "message": "PLZ vorhanden, Ort fehlt noch.",
            "source": "local",
        }
    if city and not zip_code and _clean_text(country_code).upper() in {"DE", "AT", "CH"}:
        return {
            "status": "partial",
            "message": "Ort vorhanden, aber die PLZ fehlt noch.",
            "source": "local",
        }
    return {"status": "", "message": "", "source": "local"}


def _request_json(url: str, headers: dict[str, str], timeout: int) -> object:
    req = url_request.Request(url=url, headers=headers, method="GET")
    with url_request.urlopen(req, timeout=timeout) as response:
        payload = (response.read() or b"").decode("utf-8", errors="replace").strip()
    return json.loads(payload) if payload else {}


def validate_address(
    *,
    street: str | None,
    house_no: str | None,
    zip_code: str | None,
    city: str | None,
    country_code: str | None = "DE",
    timeout: int = 6,
) -> dict[str, object]:
    street_clean = _clean_text(street)
    house_clean = _clean_text(house_no)
    zip_clean = _clean_text(zip_code)
    city_clean = _clean_text(city)
    country_clean = _clean_text(country_code).upper() or "DE"
    if not any((street_clean, house_clean, zip_clean, city_clean)):
        return {
            "status": "",
            "message": "",
            "source": "",
        }
    if not street_clean or not city_clean:
        local = _address_local_validation(street_clean, house_clean, zip_clean, city_clean, country_clean)
        if local.get("status"):
            return local
        return {
            "status": "partial",
            "message": "Fuer eine Online-Pruefung werden mindestens Strasse und Ort benoetigt.",
            "source": "local",
        }
    local = _address_local_validation(street_clean, house_clean, zip_clean, city_clean, country_clean)
    if str(local.get("status") or "") == "invalid":
        return local
    query = {
        "street": _clean_text(f"{street_clean} {house_clean}"),
        "city": city_clean,
        "postalcode": zip_clean,
        "country": country_clean,
        "format": "jsonv2",
        "addressdetails": "1",
        "limit": "5",
    }
    if len(country_clean) == 2:
        query["countrycodes"] = country_clean.lower()
    url = f"{ADDRESS_URL}?{urlencode(query)}"
    headers = {
        "Accept": "application/json",
        "User-Agent": ADDRESS_USER_AGENT,
    }
    try:
        response = _request_json(url, headers, timeout)
        if isinstance(response, dict) and isinstance(response.get("results"), list):
            rows = response.get("results") or []
        elif isinstance(response, list):
            rows = response
        else:
            rows = []
    except url_error.HTTPError as exc:
        return {
            "status": "unknown",
            "message": f"Adresspruefung aktuell nicht verfuegbar ({exc.code}).",
            "source": "nominatim",
        }
    except Exception:
        return {
            "status": "unknown",
            "message": "Adresspruefung aktuell nicht erreichbar.",
            "source": "nominatim",
        }
    best_row: dict[str, object] | None = None
    best_score = -1
    for row in rows:
        if not isinstance(row, dict):
            continue
        address = row.get("address")
        if not isinstance(address, dict):
            address = {}
        result_street = _clean_text(address.get("road") or address.get("pedestrian") or address.get("footway"))
        result_house_no = _clean_text(address.get("house_number"))
        result_zip = _clean_text(address.get("postcode"))
        result_city = _clean_text(
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("hamlet")
        )
        result_country = _clean_text(address.get("country_code")).upper() or country_clean
        score = 0
        critical_mismatch = False
        if _normalize_key(result_street) == _normalize_key(street_clean):
            score += 4
        elif _normalize_key(street_clean) in _normalize_key(result_street) or _normalize_key(result_street) in _normalize_key(street_clean):
            score += 2
        if result_house_no and result_house_no == house_clean:
            score += 2
        elif house_clean and result_house_no and result_house_no != house_clean:
            critical_mismatch = True
            score -= 3
        if zip_clean and result_zip == zip_clean:
            score += 3
        elif zip_clean and result_zip and result_zip != zip_clean:
            critical_mismatch = True
            score -= 4
        if _normalize_key(result_city) == _normalize_key(city_clean):
            score += 3
        elif _normalize_key(city_clean) in _normalize_key(result_city) or _normalize_key(result_city) in _normalize_key(city_clean):
            score += 1
        if result_country == country_clean:
            score += 1
        if score > best_score:
            best_score = score
            best_row = {
                "status": "review",
                "message": _clean_text(row.get("display_name")) or "Adresse bitte pruefen.",
                "source": "nominatim",
                "normalized_street": result_street or street_clean,
                "normalized_house_no": result_house_no or house_clean,
                "normalized_zip_code": result_zip or zip_clean,
                "normalized_city": result_city or city_clean,
                "normalized_country_code": result_country or country_clean,
                "critical_mismatch": critical_mismatch,
            }
    if best_row is None:
        return {
            "status": "review",
            "message": "Adresse wurde online nicht bestaetigt.",
            "source": "nominatim",
            "normalized_street": street_clean,
            "normalized_house_no": house_clean,
            "normalized_zip_code": zip_clean,
            "normalized_city": city_clean,
            "normalized_country_code": country_clean,
        }
    if best_score >= 10 and not bool(best_row.get("critical_mismatch")):
        best_row["status"] = "valid"
        best_row["message"] = "Adresse bestaetigt."
    elif best_score >= 7:
        best_row["status"] = "review"
        best_row["message"] = "Adresse gefunden, Schreibweise bitte pruefen."
    else:
        best_row["status"] = "review"
        best_row["message"] = "Adresse nur unscharf gefunden, bitte pruefen."
    return best_row


def _suggest_email_domain(domain: str, known_domains: set[str]) -> str:
    normalized = _normalize_domain(domain)
    if not normalized:
        return ""
    if normalized in COMMON_EMAIL_DOMAIN_CORRECTIONS:
        return COMMON_EMAIL_DOMAIN_CORRECTIONS[normalized]
    candidates = sorted({normalized, *COMMON_EMAIL_DOMAINS, *known_domains})
    matches = difflib.get_close_matches(normalized, candidates, n=1, cutoff=0.78)
    suggestion = matches[0] if matches else ""
    if suggestion == normalized:
        return ""
    return suggestion


def _resolve_dns_json(name: str, record_type: str, timeout: int) -> dict[str, object]:
    last_exc: Exception | None = None
    for endpoint in DNS_JSON_ENDPOINTS:
        params = {"name": name, "type": record_type}
        headers = {"Accept": "application/dns-json", "User-Agent": ADDRESS_USER_AGENT}
        try:
            return _request_json(f"{endpoint}?{urlencode(params)}", headers, timeout)
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    return {}


def _resolve_mail_hosts(domain: str, timeout: int) -> dict[str, object]:
    normalized = _normalize_domain(domain)
    if not normalized:
        return {"status": "invalid", "message": "Domain fehlt.", "mx_hosts": []}
    try:
        mx_payload = _resolve_dns_json(normalized, "MX", timeout)
        answers = mx_payload.get("Answer")
        hosts: list[str] = []
        if isinstance(answers, list):
            for row in answers:
                if not isinstance(row, dict):
                    continue
                data = _clean_text(row.get("data"))
                if not data:
                    continue
                parts = data.split()
                host = parts[-1].rstrip(".")
                if host and host not in hosts:
                    hosts.append(host)
        if hosts:
            return {"status": "valid", "message": "MX-Eintrag gefunden.", "mx_hosts": hosts}
        a_payload = _resolve_dns_json(normalized, "A", timeout)
        a_answers = a_payload.get("Answer")
        if isinstance(a_answers, list) and a_answers:
            return {"status": "valid", "message": "Domain mit A-Record gefunden.", "mx_hosts": [normalized]}
        return {"status": "invalid", "message": "Die Mail-Domain hat keinen MX- oder A-Record.", "mx_hosts": []}
    except Exception:
        try:
            socket.getaddrinfo(normalized, 25)
            return {"status": "valid", "message": "Domain ueber DNS erreichbar.", "mx_hosts": [normalized]}
        except Exception:
            return {"status": "unknown", "message": "Mail-Domain konnte nicht geprueft werden.", "mx_hosts": []}


def _smtp_probe_mailbox(email_value: str, mx_hosts: list[str], timeout: int) -> dict[str, object]:
    if not mx_hosts:
        return {"status": "unknown", "message": "Kein Zielserver fuer Mailbox-Pruefung bekannt."}
    for host in mx_hosts[:2]:
        try:
            with smtplib.SMTP(host, 25, timeout=timeout) as smtp:
                smtp.ehlo_or_helo_if_needed()
                smtp.mail("")
                code, response = smtp.rcpt(email_value)
            response_text = _clean_text(response.decode("utf-8", errors="replace") if isinstance(response, bytes) else response)
            if code in (250, 251):
                return {"status": "valid", "message": f"Postfach vom Server bestaetigt ({host})."}
            if code == 252:
                return {"status": "unknown", "message": f"Server akzeptiert die Adresse, bestaetigt das Postfach aber nicht ({host})."}
            if code in (550, 551, 553):
                return {"status": "undeliverable", "message": response_text or f"Server lehnt das Postfach ab ({host})."}
            if code in (421, 450, 451, 452, 454):
                return {"status": "unknown", "message": response_text or f"Server prueft das Postfach derzeit nicht ({host})."}
            return {"status": "unknown", "message": response_text or f"Server-Antwort {code} von {host}."}
        except Exception:
            continue
    return {"status": "unknown", "message": "Mailbox konnte per SMTP nicht bestaetigt werden."}


def validate_email_address(email_value: str | None, *, known_domains: set[str] | None = None, timeout: int = 6) -> dict[str, object]:
    email_clean = _clean_text(email_value).lower()
    if not email_clean:
        return {"status": "", "message": "", "suggestion": ""}
    if "@" not in email_clean or email_clean.count("@") != 1:
        return {"status": "invalid", "message": "E-Mail-Adresse ist formal ungueltig.", "suggestion": ""}
    if not EMAIL_REGEX.match(email_clean) or ".." in email_clean:
        return {"status": "invalid", "message": "E-Mail-Adresse ist formal ungueltig.", "suggestion": ""}
    local_part, domain = email_clean.rsplit("@", 1)
    if local_part.startswith(".") or local_part.endswith("."):
        return {"status": "invalid", "message": "E-Mail-Adresse ist formal ungueltig.", "suggestion": ""}
    domain = _normalize_domain(domain)
    suggestion_domain = _suggest_email_domain(domain, known_domains or set())
    if suggestion_domain:
        return {
            "status": "review",
            "message": f"Domain sieht nach Tippfehler aus. Meinst du {local_part}@{suggestion_domain}?",
            "suggestion": f"{local_part}@{suggestion_domain}",
        }
    domain_check = _resolve_mail_hosts(domain, timeout)
    if str(domain_check.get("status") or "") == "invalid":
        return {"status": "invalid", "message": str(domain_check.get("message") or "Mail-Domain ist ungueltig."), "suggestion": ""}
    mailbox_check = _smtp_probe_mailbox(email_clean, list(domain_check.get("mx_hosts") or []), timeout) if str(domain_check.get("status") or "") == "valid" else {"status": "unknown", "message": str(domain_check.get("message") or "")}
    mailbox_status = str(mailbox_check.get("status") or "")
    if mailbox_status == "undeliverable":
        return {"status": "undeliverable", "message": str(mailbox_check.get("message") or "Postfach wurde abgelehnt."), "suggestion": ""}
    if mailbox_status == "valid":
        return {"status": "valid", "message": str(mailbox_check.get("message") or "E-Mail-Adresse bestaetigt."), "suggestion": ""}
    if str(domain_check.get("status") or "") == "valid":
        return {
            "status": "unknown",
            "message": str(mailbox_check.get("message") or "Domain ist gueltig, Postfach konnte aber nicht sicher bestaetigt werden."),
            "suggestion": "",
        }
    return {"status": "unknown", "message": str(domain_check.get("message") or "E-Mail-Adresse konnte nicht vollstaendig geprueft werden."), "suggestion": ""}
