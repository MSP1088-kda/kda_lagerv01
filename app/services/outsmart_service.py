from __future__ import annotations

import json
from urllib import error as url_error, request as url_request
from urllib.parse import urlencode, urlsplit


def _extract_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("workorders", "Workorders", "materials", "relations", "results", "items", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if payload:
            return [payload]
    return []


def _extract_single(payload) -> dict:
    rows = _extract_rows(payload)
    return rows[0] if rows else (payload if isinstance(payload, dict) else {})


def request_json(
    settings: dict[str, str | bool],
    *,
    endpoint: str,
    method: str = "GET",
    query: dict[str, str] | None = None,
    payload: dict | None = None,
):
    host = str(settings.get("host") or "").strip().rstrip("/")
    bearer = str(settings.get("bearer") or "").strip()
    token = str(settings.get("token") or "").strip()
    software_token = str(settings.get("software_token") or "").strip()
    if not host or not token or not software_token:
        raise ValueError("OutSmart ist nicht vollständig konfiguriert.")
    params = dict(query or {})
    params["token"] = token
    params["software_token"] = software_token
    url = f"{host}/{str(endpoint or '').lstrip('/')}"
    if params:
        url = f"{url}?{urlencode(params)}"
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
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
        raise ValueError(f"OutSmart-Fehler {exc.code}: {body.decode('utf-8', errors='replace')}")
    except Exception as exc:
        raise ValueError(f"OutSmart nicht erreichbar: {exc}")
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def build_deep_link(settings: dict[str, str | bool], *, entity_type: str, row_id: str | None = None, external_key: str | None = None) -> str:
    explicit = str(settings.get("portal_url") or "").strip()
    if explicit:
        base = explicit.rstrip("/")
    else:
        host = str(settings.get("host") or "").strip().rstrip("/")
        if not host:
            return ""
        path = urlsplit(host).path or ""
        if "/openapi" in path:
            path = path.split("/openapi", 1)[0]
            parts = urlsplit(host)
            base = f"{parts.scheme}://{parts.netloc}{path}".rstrip("/")
        else:
            base = host
    entity = str(entity_type or "").strip().lower()
    key = str(row_id or external_key or "").strip()
    if not key:
        return ""
    mapping = {
        "relation": "relations",
        "project": "projects",
        "object": "objects",
        "workorder": "workorders",
        "material": "materials",
    }
    segment = mapping.get(entity)
    if not segment:
        return ""
    return f"{base}/{segment}/{key}"


def fetch_relations(settings: dict[str, str | bool]):
    return request_json(settings, endpoint="GetRelations", method="GET")


def fetch_projects(settings: dict[str, str | bool]):
    return request_json(settings, endpoint="GetProjects", method="GET")


def fetch_objects(settings: dict[str, str | bool]):
    return request_json(settings, endpoint="GetObjects", method="GET")


def fetch_workorders(settings: dict[str, str | bool], status: str = "", update_status: bool = False):
    query: dict[str, str] = {}
    status_clean = str(status or "").strip()
    if status_clean:
        query["status"] = status_clean
    if update_status:
        query["update_status"] = "true"
    return request_json(settings, endpoint="GetWorkorders", method="GET", query=query or None)


def fetch_workorder(settings: dict[str, str | bool], row_id_or_workorder_no: str, update_status: bool = False):
    raw = str(row_id_or_workorder_no or "").strip()
    query: dict[str, str] = {}
    if raw.isdigit():
        query["row_id"] = raw
    else:
        query["workorder_no"] = raw
    if update_status:
        query["update_status"] = "true"
    return request_json(settings, endpoint="GetWorkorder", method="GET", query=query)


def push_material(settings: dict[str, str | bool], payload_row: dict):
    return request_json(settings, endpoint="PostMaterials", method="POST", payload={"Materials": [payload_row]})


def push_relation(settings: dict[str, str | bool], payload_row: dict):
    return request_json(settings, endpoint="PostRelations", method="POST", payload={"Relations": [payload_row]})


def push_project(settings: dict[str, str | bool], payload_row: dict):
    return request_json(settings, endpoint="PostProjects", method="POST", payload={"Projects": [payload_row]})


def push_workorder(settings: dict[str, str | bool], payload_row: dict):
    return request_json(settings, endpoint="PostWorkorders", method="POST", payload={"Workorders": [payload_row]})


def update_workorder_schedule(settings: dict[str, str | bool], row_id: str, payload_row: dict):
    payload = {"RowId": str(row_id or "").strip(), **dict(payload_row or {})}
    return request_json(settings, endpoint="UpdateWorkorderSchedule", method="POST", payload=payload)


def test_connection(settings: dict[str, str | bool]):
    return fetch_workorders(settings, status="Compleet", update_status=False)


def post_materials(settings: dict[str, str | bool], rows: list[dict]):
    return request_json(settings, endpoint="PostMaterials", method="POST", payload={"Materials": rows})


def post_relations(settings: dict[str, str | bool], rows: list[dict]):
    return request_json(settings, endpoint="PostRelations", method="POST", payload={"Relations": rows})


def post_workorders(settings: dict[str, str | bool], rows: list[dict]):
    return request_json(settings, endpoint="PostWorkorders", method="POST", payload={"Workorders": rows})


def get_completed_workorders(settings: dict[str, str | bool], limit: int = 20) -> list[dict]:
    payload = fetch_workorders(settings, status="Compleet", update_status=False)
    rows = _extract_rows(payload)
    return rows[: max(1, int(limit))]


def mark_workorder_processed(settings: dict[str, str | bool], row_id: str) -> dict | list | str:
    return fetch_workorder(settings, str(row_id), update_status=True)


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
