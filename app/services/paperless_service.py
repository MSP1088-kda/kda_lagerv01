from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib import error as url_error, request as url_request
from urllib.parse import urlencode


def _paperless_headers(settings: dict[str, str | bool], *, with_json: bool = True) -> dict[str, str]:
    token = str(settings.get("token") or "").strip()
    if not token:
        raise ValueError("Paperless-Token fehlt.")
    headers = {"Authorization": f"Token {token}"}
    if with_json:
        headers["Accept"] = "application/json"
    return headers


def _paperless_url(base_url: str, path: str) -> str:
    return f"{str(base_url or '').rstrip('/')}/{str(path or '').lstrip('/')}"


def request_json(
    settings: dict[str, str | bool],
    *,
    method: str,
    path: str,
    query: dict[str, str] | None = None,
    payload: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict | list | str:
    base_url = str(settings.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("Paperless Base-URL fehlt.")
    url = _paperless_url(base_url, path)
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = _paperless_headers(settings, with_json=True)
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(url=url, data=data, headers=headers, method=str(method or "GET").upper())
    try:
        with url_request.urlopen(req, timeout=20) as resp:
            raw = resp.read() or b""
    except url_error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        msg = (body.decode("utf-8", errors="replace") or str(exc)).strip()
        raise ValueError(f"Paperless-Fehler {exc.code}: {msg}")
    except Exception as exc:
        raise ValueError(f"Paperless nicht erreichbar: {exc}")
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return text


def _safe_filename(filename: str, fallback: str = "dokument") -> str:
    text = "".join(ch for ch in str(filename or "") if ch.isalnum() or ch in ("-", "_", "."))
    return text.strip(".") or fallback


def _encode_multipart(document_field: str, filename: str, mime: str, payload: bytes, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----kda-{uuid.uuid4().hex}"
    body = bytearray()
    for key, value in fields.items():
        text = (value or "").strip()
        if not text:
            continue
        body.extend(f"--{boundary}\\r\\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\\r\\n\\r\\n'.encode("utf-8"))
        body.extend(text.encode("utf-8"))
        body.extend(b"\\r\\n")
    body.extend(f"--{boundary}\\r\\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{document_field}"; filename="{_safe_filename(filename, "dokument")}"\\r\\n'
            f"Content-Type: {mime or 'application/octet-stream'}\\r\\n\\r\\n"
        ).encode("utf-8")
    )
    body.extend(payload)
    body.extend(b"\\r\\n")
    body.extend(f"--{boundary}--\\r\\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def test_connection(settings: dict[str, str | bool]) -> dict | list | str:
    return request_json(settings, method="GET", path="/api/documents/", query={"page_size": "1"})


def list_recent_supplier_documents(settings: dict[str, str | bool], limit: int = 50) -> list[dict]:
    return list_documents(settings, limit=limit)


def list_documents(settings: dict[str, str | bool], *, limit: int = 50, query: str | None = None) -> list[dict]:
    payload = request_json(
        settings,
        method="GET",
        path="/api/documents/",
        query={
            "page_size": str(max(1, int(limit))),
            "ordering": "-created_date",
            **({"query": str(query).strip()} if str(query or "").strip() else {}),
        },
    )
    if isinstance(payload, dict):
        rows = payload.get("results")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def get_document(settings: dict[str, str | bool], document_id: str | int) -> dict:
    payload = request_json(settings, method="GET", path=f"/api/documents/{document_id}/")
    return payload if isinstance(payload, dict) else {}


def download_document(settings: dict[str, str | bool], document_id: str | int) -> tuple[bytes, str]:
    base_url = str(settings.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("Paperless Base-URL fehlt.")
    headers = _paperless_headers(settings, with_json=False)
    req = url_request.Request(
        url=_paperless_url(base_url, f"/api/documents/{document_id}/download/"),
        headers=headers,
        method="GET",
    )
    try:
        with url_request.urlopen(req, timeout=30) as resp:
            payload = resp.read() or b""
            content_type = str(resp.headers.get("Content-Type") or "application/octet-stream")
    except url_error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        raise ValueError(f"Paperless-Download fehlgeschlagen ({exc.code}): {body.decode('utf-8', errors='replace')}")
    except Exception as exc:
        raise ValueError(f"Paperless-Download fehlgeschlagen: {exc}")
    return payload, content_type


def upload_document(file_path: str | Path, settings: dict[str, str | bool], **metadata) -> dict[str, str]:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError("Datei für Paperless-Upload wurde nicht gefunden.")
    payload = path.read_bytes()
    fields = {
        "title": str(metadata.get("title") or path.name),
        "tags": str(metadata.get("tags") or settings.get("tags") or ""),
        "document_type": str(metadata.get("document_type") or settings.get("document_type") or ""),
        "correspondent": str(metadata.get("correspondent") or settings.get("correspondent") or ""),
        "created": str(metadata.get("created") or ""),
    }
    body, content_type = _encode_multipart(
        "document",
        path.name,
        str(metadata.get("mime") or "application/octet-stream"),
        payload,
        fields,
    )
    base_url = str(settings.get("base_url") or "").strip()
    headers = _paperless_headers(settings, with_json=True)
    headers["Content-Type"] = content_type
    req = url_request.Request(
        url=_paperless_url(base_url, "/api/documents/post_document/"),
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=30) as resp:
            text = (resp.read() or b"").decode("utf-8", errors="replace").strip()
    except url_error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        raise ValueError(f"Paperless-Upload fehlgeschlagen ({exc.code}): {body.decode('utf-8', errors='replace')}")
    except Exception as exc:
        raise ValueError(f"Paperless-Upload fehlgeschlagen: {exc}")

    response_payload: dict = {}
    if text:
        try:
            response_payload = json.loads(text)
        except Exception:
            response_payload = {"raw": text}
    task_id = str(response_payload.get("task_id") or response_payload.get("task") or "").strip()
    document_id = str(response_payload.get("document_id") or "").strip()
    if task_id and not document_id:
        task_info = request_json(settings, method="GET", path="/api/tasks/", query={"task_id": task_id})
        if isinstance(task_info, dict):
            results = task_info.get("results")
            if isinstance(results, list) and results:
                first = results[0] if isinstance(results[0], dict) else {}
                related = first.get("related_document")
                if related is not None:
                    document_id = str(related).strip()
    return {"task_id": task_id, "document_id": document_id}


def update_document_metadata(document_id: str | int, settings: dict[str, str | bool], **metadata) -> dict | list | str:
    clean_payload = {}
    for key, value in metadata.items():
        if value in (None, ""):
            continue
        clean_payload[key] = value
    return request_json(
        settings,
        method="PATCH",
        path=f"/api/documents/{document_id}/",
        payload=clean_payload,
        extra_headers={"Content-Type": "application/json"},
    )


def build_document_url(settings: dict[str, str | bool], document_id: str | int) -> str:
    base_url = str(settings.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/documents/{document_id}/details/"
