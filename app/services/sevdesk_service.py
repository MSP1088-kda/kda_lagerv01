from __future__ import annotations

import json
from urllib import error as url_error, request as url_request
from urllib.parse import urlencode, urlsplit


def _sevdesk_url(base_url: str, path: str) -> str:
    return f"{str(base_url or '').rstrip('/')}/{str(path or '').lstrip('/')}"


def _headers(settings: dict[str, str | bool], *, with_json: bool = True) -> dict[str, str]:
    token = str(settings.get("api_token") or settings.get("token") or "").strip()
    if not token:
        raise ValueError("sevDesk API-Token fehlt.")
    headers = {
        "Authorization": token,
        # Cloudflare blocks the default Python-urllib signature on my.sevdesk.de with error 1010.
        # A stable application user agent yields the expected API response codes instead.
        "User-Agent": "KDA-Lager/0.1 (+https://localhost; sevdesk-api-client)",
    }
    if with_json:
        headers["Accept"] = "application/json"
    return headers


def _extract_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("objects", "object", "results", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                return [value]
        if payload:
            return [payload]
    return []


def _first_row(payload) -> dict:
    rows = _extract_rows(payload)
    return rows[0] if rows else (payload if isinstance(payload, dict) else {})


def first_value(payload, keys: tuple[str, ...]) -> str:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        for value in payload.values():
            found = first_value(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = first_value(item, keys)
            if found:
                return found
    return ""


def _ensure_push_allowed(settings: dict[str, str | bool]) -> None:
    if bool(settings.get("push_blocked")):
        raise ValueError("sevDesk-Schreibzugriff ist deaktiviert. Es sind aktuell nur Lesezugriffe erlaubt.")


def request_json(
    settings: dict[str, str | bool],
    *,
    method: str,
    path: str,
    query: dict[str, str | int | float] | None = None,
    payload: dict | list | None = None,
):
    base_url = str(settings.get("base_url") or "https://my.sevdesk.de/api/v1").strip()
    if not base_url:
        raise ValueError("sevDesk Base-URL fehlt.")
    url = _sevdesk_url(base_url, path)
    if query:
        encoded = {key: str(value) for key, value in query.items() if value not in (None, "")}
        if encoded:
            url = f"{url}?{urlencode(encoded)}"
    headers = _headers(settings, with_json=True)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(url=url, data=data, headers=headers, method=str(method or "GET").upper())
    try:
        with url_request.urlopen(req, timeout=30) as resp:
            raw = resp.read() or b""
    except url_error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        body_text = body.decode("utf-8", errors="replace") or str(exc)
        if exc.code == 403 and "cloudflare" in body_text.lower() and "1010" in body_text:
            raise ValueError(
                "sevDesk-Zugriff von Cloudflare abgewiesen (1010). "
                "Der Client wurde blockiert, bevor die API antworten konnte. "
                "Bitte Verbindung erneut testen; falls der Fehler bleibt, IP-/WAF-Sperre bei sevDesk prüfen."
            )
        raise ValueError(f"sevDesk-Fehler {exc.code}: {body_text}")
    except Exception as exc:
        raise ValueError(f"sevDesk nicht erreichbar: {exc}")
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def _request_candidates(
    settings: dict[str, str | bool],
    *,
    method: str,
    paths: tuple[str, ...],
    query: dict[str, str | int | float] | None = None,
    payload: dict | list | None = None,
):
    errors: list[str] = []
    for path in paths:
        try:
            return request_json(settings, method=method, path=path, query=query, payload=payload)
        except ValueError as exc:
            message = str(exc)
            errors.append(message)
            if " 404:" in message or " 405:" in message:
                continue
            raise
    raise ValueError(errors[-1] if errors else "sevDesk-Endpunkt nicht erreichbar.")


def build_api_url(settings: dict[str, str | bool], path: str) -> str:
    base_url = str(settings.get("base_url") or "https://my.sevdesk.de/api/v1").strip()
    if not base_url:
        return ""
    return _sevdesk_url(base_url, path)


def build_web_url(
    settings: dict[str, str | bool],
    *,
    entity_type: str,
    object_id: str | int | None = None,
    document_type: str | None = None,
) -> str:
    raw_id = str(object_id or "").strip()
    if not raw_id:
        return ""
    base_url = str(settings.get("base_url") or "https://my.sevdesk.de/api/v1").strip()
    if not base_url:
        return ""
    parts = urlsplit(base_url)
    path = (parts.path or "").rstrip("/")
    for suffix in ("/api/v1", "/api"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    base = f"{parts.scheme}://{parts.netloc}{path}".rstrip("/")
    if not base:
        return ""
    entity = str(entity_type or "").strip().lower()
    document_key = str(document_type or "").strip().upper()
    if entity == "invoice":
        return f"{base}/fi/detail/type/{document_key or 'RE'}/id/{raw_id}"
    if entity in {"offer", "order"}:
        return f"{base}/om/detail/type/{document_key or 'AN'}/id/{raw_id}"
    return ""


def test_connection(settings: dict[str, str | bool]):
    return _request_candidates(
        settings,
        method="GET",
        paths=("/CheckAccount", "/Contact"),
        query={"limit": 1},
    )


def get_bookkeeping_system_version(settings: dict[str, str | bool]) -> str:
    payload = _request_candidates(
        settings,
        method="GET",
        paths=(
            "/Tools/bookkeepingSystemVersion",
            "/Export/bookkeepingSystemVersion",
            "/Export/getBookkeepingSystemVersion",
        ),
    )
    return first_value(payload, ("bookkeepingSystemVersion", "version", "value", "text"))


def find_contact(
    settings: dict[str, str | bool],
    *,
    customer_number: str = "",
    name: str = "",
    city: str = "",
    zip_code: str = "",
    email: str = "",
    limit: int = 20,
) -> list[dict]:
    query: dict[str, str | int] = {"limit": max(1, int(limit))}
    if customer_number:
        query["customerNumber"] = customer_number
    if name:
        query["name"] = name
    if city:
        query["city"] = city
    if zip_code:
        query["zip"] = zip_code
    if email:
        query["email"] = email
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/Contact", "/Contact/Factory/getContacts"),
        query=query,
    )
    return _extract_rows(payload)


def create_or_update_contact(settings: dict[str, str | bool], payload_row: dict, contact_id: str | int | None = None):
    _ensure_push_allowed(settings)
    if str(contact_id or "").strip():
        return _request_candidates(
            settings,
            method="PUT",
            paths=(f"/Contact/{contact_id}", f"/Contact/{contact_id}/Factory/update"),
            payload=payload_row,
        )
    return _request_candidates(
        settings,
        method="POST",
        paths=("/Contact", "/Contact/Factory/save"),
        payload=payload_row,
    )


def create_order(settings: dict[str, str | bool], payload_row: dict):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="POST",
        paths=("/Order", "/Order/Factory/save"),
        payload=payload_row,
    )


def send_order(settings: dict[str, str | bool], order_id: str | int, payload_row: dict | None = None):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="POST",
        paths=(
            f"/Order/{order_id}/sendBy",
            f"/Order/{order_id}/sendViaEmail",
            f"/Order/{order_id}/Factory/sendBy",
        ),
        payload=payload_row or {},
    )


def create_invoice(settings: dict[str, str | bool], payload_row: dict):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="POST",
        paths=("/Invoice/Factory/saveInvoice", "/Invoice/Factory/save", "/Invoice"),
        payload=payload_row,
    )


def send_invoice(settings: dict[str, str | bool], invoice_id: str | int, payload_row: dict | None = None):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="POST",
        paths=(
            f"/Invoice/{invoice_id}/sendBy",
            f"/Invoice/{invoice_id}/sendViaEmail",
            f"/Invoice/{invoice_id}/Factory/sendBy",
        ),
        payload=payload_row or {},
    )


def create_voucher(settings: dict[str, str | bool], payload_row: dict):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="POST",
        paths=("/Voucher/Factory/saveVoucher", "/Voucher/Factory/save", "/Voucher"),
        payload=payload_row,
    )


def book_voucher(settings: dict[str, str | bool], voucher_id: str | int, payload_row: dict):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="PUT",
        paths=(
            f"/Voucher/{voucher_id}/bookAmount",
            f"/Voucher/{voucher_id}/Factory/bookAmount",
        ),
        payload=payload_row,
    )


def book_invoice(settings: dict[str, str | bool], invoice_id: str | int, payload_row: dict):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="PUT",
        paths=(
            f"/Invoice/{invoice_id}/bookAmount",
            f"/Invoice/{invoice_id}/Factory/bookAmount",
        ),
        payload=payload_row,
    )


def get_check_accounts(settings: dict[str, str | bool]) -> list[dict]:
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/CheckAccount", "/CheckAccount/Factory/getList"),
        query={"limit": 200},
    )
    return _extract_rows(payload)


def get_transactions(
    settings: dict[str, str | bool],
    *,
    check_account_id: str | int | None = None,
    start_date: str = "",
    end_date: str = "",
    amount: str = "",
    search: str = "",
    is_booked: bool | None = None,
    only_credit: bool | None = None,
    only_debit: bool | None = None,
    limit: int = 120,
):
    query: dict[str, str | int] = {"limit": max(1, int(limit))}
    if str(check_account_id or "").strip():
        query["checkAccount[id]"] = str(check_account_id)
        query["checkAccount[objectName]"] = "CheckAccount"
    if start_date:
        query["startDate"] = start_date
    if end_date:
        query["endDate"] = end_date
    if search:
        query["payeePayerName"] = search
        query["paymtPurpose"] = search
    if is_booked is not None:
        query["isBooked"] = "true" if is_booked else "false"
    if only_credit is not None:
        query["onlyCredit"] = "true" if only_credit else "false"
    if only_debit is not None:
        query["onlyDebit"] = "true" if only_debit else "false"
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/CheckAccountTransaction", "/CheckAccountTransaction/Factory/getList"),
        query=query,
    )
    rows = _extract_rows(payload)
    if str(amount or "").strip():
        target = str(amount or "").strip().replace(" ", "").replace(",", ".")
        try:
            target_value = abs(round(float(target), 2))
        except Exception:
            target_value = None
        if target_value is not None:
            filtered: list[dict] = []
            for row in rows:
                raw_amount = first_value(row, ("amount", "sum", "value", "Value"))
                try:
                    amount_value = abs(round(float(str(raw_amount or "0").replace(" ", "").replace(",", ".")), 2))
                except Exception:
                    amount_value = None
                if amount_value is not None and abs(amount_value - target_value) < 0.01:
                    filtered.append(row)
            rows = filtered
    return rows


def create_transaction(settings: dict[str, str | bool], payload_row: dict):
    _ensure_push_allowed(settings)
    return _request_candidates(
        settings,
        method="POST",
        paths=("/CheckAccountTransaction", "/CheckAccountTransaction/Factory/save"),
        payload=payload_row,
    )


def get_receipt_guidance_accounts(
    settings: dict[str, str | bool],
    *,
    receipt_kind: str = "",
    account_number: str = "",
    tax_rule: str = "",
) -> list[dict]:
    kind = str(receipt_kind or "").strip().lower()
    if str(account_number or "").strip():
        payload = _request_candidates(
            settings,
            method="GET",
            paths=("/ReceiptGuidance/forAccountNumber",),
            query={"accountNumber": str(account_number).strip()},
        )
        return _extract_rows(payload)
    if str(tax_rule or "").strip():
        payload = _request_candidates(
            settings,
            method="GET",
            paths=("/ReceiptGuidance/forTaxRule",),
            query={"taxRule": str(tax_rule).strip()},
        )
        return _extract_rows(payload)
    if kind == "expense":
        payload = _request_candidates(
            settings,
            method="GET",
            paths=("/ReceiptGuidance/forExpense", "/ReceiptGuidance/forAllAccounts"),
        )
        return _extract_rows(payload)
    if kind == "revenue":
        payload = _request_candidates(
            settings,
            method="GET",
            paths=("/ReceiptGuidance/forRevenue", "/ReceiptGuidance/forAllAccounts"),
        )
        return _extract_rows(payload)
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/ReceiptGuidance/forAllAccounts",),
    )
    return _extract_rows(payload)


def get_next_customer_number(settings: dict[str, str | bool]) -> str:
    payload = _request_candidates(
        settings,
        method="GET",
        paths=(
            "/Contact/Factory/getNextCustomerNumber",
            "/Contact/getNextCustomerNumber",
        ),
    )
    return first_value(payload, ("customerNumber", "number", "value"))


def check_customer_number_availability(settings: dict[str, str | bool], customer_number: str) -> bool:
    payload = _request_candidates(
        settings,
        method="GET",
        paths=(
            "/Contact/Factory/checkCustomerNumberAvailability",
            "/Contact/checkCustomerNumberAvailability",
        ),
        query={"customerNumber": customer_number},
    )
    raw = first_value(payload, ("available", "isAvailable", "value", "status"))
    if not raw:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "ja", "available")


def list_contacts(settings: dict[str, str | bool], *, limit: int = 1000, offset: int = 0) -> list[dict]:
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/Contact", "/Contact/Factory/getContacts"),
        query={"limit": max(1, int(limit)), "offset": max(0, int(offset))},
    )
    return _extract_rows(payload)


def get_contact(settings: dict[str, str | bool], contact_id: str | int, *, embed: str = "") -> dict:
    payload = _request_candidates(
        settings,
        method="GET",
        paths=(f"/Contact/{contact_id}",),
        query={"embed": embed} if str(embed or "").strip() else None,
    )
    return _first_row(payload)


def list_contact_addresses(
    settings: dict[str, str | bool],
    *,
    contact_id: str | int = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    query: dict[str, str | int] = {"limit": max(1, int(limit)), "offset": max(0, int(offset))}
    if str(contact_id or "").strip():
        query["contact[id]"] = str(contact_id).strip()
        query["contact[objectName]"] = "Contact"
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/ContactAddress", "/ContactAddress/Factory/getList"),
        query=query,
    )
    return _extract_rows(payload)


def list_orders(
    settings: dict[str, str | bool],
    *,
    limit: int = 1000,
    offset: int = 0,
    contact_id: str | int = "",
    embed: str = "",
    status: str = "",
    count_all: bool = False,
) -> list[dict]:
    query: dict[str, str | int] = {"limit": max(1, int(limit)), "offset": max(0, int(offset))}
    if str(contact_id or "").strip():
        query["contact[id]"] = str(contact_id).strip()
        query["contact[objectName]"] = "Contact"
    if str(embed or "").strip():
        query["embed"] = str(embed).strip()
    if str(status or "").strip():
        query["status"] = str(status).strip()
    if count_all:
        query["countAll"] = "true"
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/Order", "/Order/Factory/getList"),
        query=query,
    )
    return _extract_rows(payload)


def list_invoices(
    settings: dict[str, str | bool],
    *,
    limit: int = 1000,
    offset: int = 0,
    contact_id: str | int = "",
    embed: str = "",
    status: str = "",
    count_all: bool = False,
    delinquent: bool = False,
) -> list[dict]:
    query: dict[str, str | int] = {"limit": max(1, int(limit)), "offset": max(0, int(offset))}
    if str(contact_id or "").strip():
        query["contact[id]"] = str(contact_id).strip()
        query["contact[objectName]"] = "Contact"
    if str(embed or "").strip():
        query["embed"] = str(embed).strip()
    if str(status or "").strip():
        query["status"] = str(status).strip()
    if count_all:
        query["countAll"] = "true"
    if delinquent:
        query["delinquent"] = "true"
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/Invoice", "/Invoice/Factory/getList"),
        query=query,
    )
    return _extract_rows(payload)


def list_vouchers(
    settings: dict[str, str | bool],
    *,
    limit: int = 1000,
    offset: int = 0,
    contact_id: str | int = "",
    embed: str = "",
    status: str = "",
    credit_debit: str = "",
    count_all: bool = False,
) -> list[dict]:
    query: dict[str, str | int] = {"limit": max(1, int(limit)), "offset": max(0, int(offset))}
    if str(contact_id or "").strip():
        query["contact[id]"] = str(contact_id).strip()
        query["contact[objectName]"] = "Contact"
    if str(embed or "").strip():
        query["embed"] = str(embed).strip()
    if str(status or "").strip():
        query["status"] = str(status).strip()
    if str(credit_debit or "").strip():
        query["creditDebit"] = str(credit_debit).strip()
    if count_all:
        query["countAll"] = "true"
    payload = _request_candidates(
        settings,
        method="GET",
        paths=("/Voucher", "/Voucher/Factory/getList"),
        query=query,
    )
    return _extract_rows(payload)


def update_export_config(settings: dict[str, str | bool], payload_row: dict):
    return _request_candidates(
        settings,
        method="POST",
        paths=(
            "/Export/updateExportConfig",
            "/Export/Factory/updateExportConfig",
        ),
        payload=payload_row,
    )


def create_datev_csv_export_job(settings: dict[str, str | bool], payload_row: dict | None = None):
    return _request_candidates(
        settings,
        method="POST",
        paths=(
            "/Export/createDatevCsvZipExportJob",
            "/Export/Factory/createDatevCsvZipExportJob",
        ),
        payload=payload_row or {},
    )


def create_datev_xml_export_job(settings: dict[str, str | bool], payload_row: dict | None = None):
    return _request_candidates(
        settings,
        method="POST",
        paths=(
            "/Export/createDatevXmlZipExportJob",
            "/Export/Factory/createDatevXmlZipExportJob",
        ),
        payload=payload_row or {},
    )


def generate_download_hash(settings: dict[str, str | bool], job_id: str | int):
    return _request_candidates(
        settings,
        method="POST",
        paths=(
            f"/Export/{job_id}/generateDownloadHash",
            f"/Export/{job_id}/Factory/generateDownloadHash",
        ),
        payload={},
    )


def get_export_progress(settings: dict[str, str | bool], job_id: str | int):
    return _request_candidates(
        settings,
        method="GET",
        paths=(
            f"/Export/{job_id}/getProgress",
            f"/Export/{job_id}/Factory/getProgress",
        ),
    )


def get_job_download_info(settings: dict[str, str | bool], job_id: str | int):
    return _request_candidates(
        settings,
        method="GET",
        paths=(
            f"/Export/{job_id}/jobDownloadInfo",
            f"/Export/{job_id}/Factory/jobDownloadInfo",
        ),
    )


def extract_object_id(payload) -> str:
    row = _first_row(payload)
    return first_value(row or payload, ("id", "ID", "objectId", "voucherId", "invoiceId", "orderId"))
