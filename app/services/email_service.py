from __future__ import annotations

import datetime as dt
import email
from email.header import decode_header
from email.message import EmailMessage as MimeEmailMessage
from email.utils import getaddresses, make_msgid, parseaddr, parsedate_to_datetime
import imaplib
import re
import smtplib
import socket
import ssl
from typing import Any
from pathlib import Path

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import CrmTimelineEvent, EmailAccount, EmailMessage, EmailOutbox, MailAttachment, MailThread
from ..utils import ensure_dirs, get_fernet
from .mail_assignment_service import normalize_subject, suggest_assignments


def decrypt_password(value_enc: str | None) -> str | None:
    if not value_enc:
        return None
    try:
        return get_fernet().decrypt(value_enc.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


def friendly_mail_error(exc: Exception) -> str:
    msg = str(exc or "").strip()
    lower = msg.lower()
    if isinstance(exc, smtplib.SMTPAuthenticationError) or "authentication" in lower or "auth" in lower or "login failed" in lower:
        return "Anmeldung fehlgeschlagen. Benutzername/Passwort prüfen."
    if "ssl" in lower or "tls" in lower or "wrong version number" in lower or "certificate" in lower:
        return "TLS/SSL-Fehler. Bitte TLS-Einstellung und Port prüfen."
    if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in lower or "timeout" in lower:
        return "Server nicht erreichbar (Zeitüberschreitung)."
    if "name or service not known" in lower or "connection refused" in lower or "nodename nor servname" in lower:
        return "Server nicht erreichbar. Host/Port prüfen."
    if isinstance(exc, imaplib.IMAP4.error):
        return "IMAP-Anmeldung oder Zugriff fehlgeschlagen."
    if msg:
        return msg
    return "Unbekannter Verbindungsfehler."


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            enc = encoding or "utf-8"
            try:
                parts.append(chunk.decode(enc, errors="replace"))
            except Exception:
                parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts).strip()


def _extract_plain_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            cdisp = (part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload is None:
                    raw = part.get_payload()
                    return str(raw or "")
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except Exception:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return str(msg.get_payload() or "")
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


def _extract_html_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            cdisp = (part.get("Content-Disposition") or "").lower()
            if ctype == "text/html" and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload is None:
                    raw = part.get_payload()
                    return str(raw or "")
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except Exception:
                    return payload.decode("utf-8", errors="replace")
        return ""
    if (msg.get_content_type() or "").lower() != "text/html":
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return str(msg.get_payload() or "")
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


def _extract_attachments(msg: email.message.Message) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for part in msg.walk():
        cdisp = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in cdisp:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = _decode_header_value(part.get_filename()) or "anhang.bin"
        rows.append(
            {
                "filename": filename,
                "mime_type": (part.get_content_type() or "application/octet-stream").lower(),
                "payload": payload,
            }
        )
    return rows


def _utcnow_naive() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=None)


def _normalize_message_id_header(value: str | None) -> str | None:
    text = str(value or "").strip().strip("<>").strip()
    return text or None


def _parse_received_datetime(value: str | None) -> dt.datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed.replace(tzinfo=None)
    except Exception:
        return None


def _mail_upload_dir() -> Path:
    return ensure_dirs()["uploads"] / "mail"


def _safe_mail_filename(filename: str | None, fallback: str = "anhang.bin") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(filename or "").strip())
    return text.strip("._") or fallback


def _save_attachment_file(message_id: int, filename: str, payload: bytes) -> str:
    base_dir = _mail_upload_dir() / str(int(message_id))
    base_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_mail_filename(filename)
    target = base_dir / safe_name
    if target.exists():
        target = base_dir / f"{target.stem}_{dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{target.suffix}"
    target.write_bytes(payload)
    return str(target.relative_to(ensure_dirs()["uploads"]))


def _addresses_csv(values: list[str]) -> str | None:
    items = [str(addr or "").strip() for _, addr in getaddresses(values) if str(addr or "").strip()]
    return ", ".join(items) if items else None


def _resolve_mail_thread(
    db: Session,
    *,
    subject: str | None,
    header_thread_id: int | None = None,
    customer_id: int | None = None,
    case_id: int | None = None,
    message_dt: dt.datetime | None = None,
) -> MailThread:
    thread = db.get(MailThread, int(header_thread_id or 0)) if int(header_thread_id or 0) > 0 else None
    subject_normalized = normalize_subject(subject)
    if thread is None:
        query = db.query(MailThread).filter(MailThread.subject_normalized == subject_normalized)
        if int(case_id or 0) > 0:
            query = query.filter(or_(MailThread.case_id == int(case_id), MailThread.case_id.is_(None)))
        elif int(customer_id or 0) > 0:
            query = query.filter(or_(MailThread.master_customer_id == int(customer_id), MailThread.master_customer_id.is_(None)))
        thread = query.order_by(MailThread.last_message_at.desc(), MailThread.id.desc()).first()
    if thread is None:
        thread = MailThread(
            subject_normalized=subject_normalized,
            master_customer_id=int(customer_id) if int(customer_id or 0) > 0 else None,
            case_id=int(case_id) if int(case_id or 0) > 0 else None,
            status="open",
            last_message_at=message_dt or _utcnow_naive(),
            created_at=_utcnow_naive(),
        )
        db.add(thread)
        db.flush()
        return thread
    if int(customer_id or 0) > 0 and int(thread.master_customer_id or 0) <= 0:
        thread.master_customer_id = int(customer_id)
    if int(case_id or 0) > 0 and int(thread.case_id or 0) <= 0:
        thread.case_id = int(case_id)
    thread.last_message_at = message_dt or thread.last_message_at or _utcnow_naive()
    db.add(thread)
    db.flush()
    return thread


def _timeline_event(
    db: Session,
    *,
    thread: MailThread | None,
    message: EmailMessage,
    title: str,
    body: str,
    event_type: str,
) -> None:
    customer_id = int(message.master_customer_id or thread.master_customer_id or 0) if thread else int(message.master_customer_id or 0)
    case_id = int(message.case_id or thread.case_id or 0) if thread else int(message.case_id or 0)
    if customer_id <= 0 and case_id <= 0:
        return
    exists = (
        db.query(CrmTimelineEvent)
        .filter(
            CrmTimelineEvent.source_system == "mail",
            CrmTimelineEvent.event_type == event_type,
            CrmTimelineEvent.external_ref == f"mail:{int(message.id)}",
        )
        .first()
    )
    if exists:
        return
    db.add(
        CrmTimelineEvent(
            case_id=case_id or None,
            master_customer_id=customer_id or None,
            source_system="mail",
            event_type=event_type,
            title=title,
            body=body,
            event_ts=message.received_at or message.sent_at or _utcnow_naive(),
            external_ref=f"mail:{int(message.id)}",
            created_at=_utcnow_naive(),
        )
    )


def _apply_assignment(
    message: EmailMessage,
    thread: MailThread,
    *,
    customer_ids: list[int],
    case_ids: list[int],
    status: str,
) -> None:
    if len(customer_ids) == 1:
        message.master_customer_id = int(customer_ids[0])
        if int(thread.master_customer_id or 0) <= 0:
            thread.master_customer_id = int(customer_ids[0])
    if len(case_ids) == 1:
        message.case_id = int(case_ids[0])
        if int(thread.case_id or 0) <= 0:
            thread.case_id = int(case_ids[0])
    message.assignment_status = status or "unassigned"
    if int(thread.master_customer_id or 0) > 0 or int(thread.case_id or 0) > 0:
        thread.status = "open" if message.direction == "in" else thread.status


def _smtp_client(account: EmailAccount):
    if not account.smtp_host or not account.smtp_port:
        raise ValueError("SMTP-Host/Port fehlen.")
    timeout = 12
    port = int(account.smtp_port)
    if bool(account.smtp_tls):
        if port == 465:
            client = smtplib.SMTP_SSL(account.smtp_host, port, timeout=timeout, context=ssl.create_default_context())
            client.ehlo()
        else:
            client = smtplib.SMTP(account.smtp_host, port, timeout=timeout)
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
    else:
        client = smtplib.SMTP(account.smtp_host, port, timeout=timeout)
        client.ehlo()
    pw = decrypt_password(account.smtp_password_enc)
    if account.smtp_username:
        client.login(account.smtp_username, pw or "")
    return client


def _imap_client(account: EmailAccount):
    if not account.imap_host or not account.imap_port:
        raise ValueError("IMAP-Host/Port fehlen.")
    timeout = 12
    if bool(account.imap_tls):
        client = imaplib.IMAP4_SSL(account.imap_host, int(account.imap_port), timeout=timeout)
    else:
        client = imaplib.IMAP4(account.imap_host, int(account.imap_port), timeout=timeout)
    pw = decrypt_password(account.imap_password_enc) or ""
    if account.imap_username:
        client.login(account.imap_username, pw)
    return client


def send_test_smtp(account: EmailAccount, send_mail: bool = False) -> dict[str, Any]:
    client = None
    try:
        client = _smtp_client(account)
        if send_mail:
            msg = MimeEmailMessage()
            msg["Subject"] = "KDA Lager SMTP-Test"
            msg["From"] = account.email
            msg["To"] = account.email
            msg.set_content("Dies ist eine automatische Testmail aus KDA Lager.")
            client.send_message(msg)
        return {"ok": True, "message": "SMTP-Verbindung erfolgreich." + (" Testmail wurde versendet." if send_mail else "")}
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass


def test_imap(account: EmailAccount) -> dict[str, Any]:
    client = None
    try:
        client = _imap_client(account)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise ValueError("INBOX konnte nicht geöffnet werden.")
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise ValueError("INBOX konnte nicht gelesen werden.")
        raw = (data[0] or b"") if data else b""
        count = len(raw.split()) if raw else 0
        return {"ok": True, "message": f"IMAP-Verbindung erfolgreich. Nachrichten in INBOX: {count}."}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass


def _resolve_send_account(db: Session, account_id: int | None) -> EmailAccount | None:
    if account_id:
        acc = db.get(EmailAccount, int(account_id))
        if acc and acc.enabled:
            return acc
    return (
        db.query(EmailAccount)
        .filter(EmailAccount.enabled == True)
        .order_by(EmailAccount.is_default.desc(), EmailAccount.id.asc())
        .first()
    )


def send_email_via_account(account: EmailAccount, to_email: str, subject: str, body_text: str) -> None:
    client = None
    try:
        client = _smtp_client(account)
        msg = MimeEmailMessage()
        msg["Subject"] = (subject or "").strip()
        msg["From"] = account.email
        msg["To"] = (to_email or "").strip()
        msg.set_content(body_text or "")
        client.send_message(msg)
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass


def send_outbox_once(db: Session, batch_size: int = 20) -> dict[str, int]:
    rows = (
        db.query(EmailOutbox)
        .filter(or_(EmailOutbox.status == "queued", EmailOutbox.status == "error"))
        .order_by(EmailOutbox.created_at.asc(), EmailOutbox.id.asc())
        .limit(max(1, int(batch_size)))
        .all()
    )
    sent = 0
    failed = 0
    for row in rows:
        account = _resolve_send_account(db, row.account_id)
        if not account:
            row.status = "error"
            row.last_error = "Kein aktives E-Mail-Konto verfügbar."
            row.attempts = int(row.attempts or 0) + 1
            db.add(row)
            failed += 1
            continue
        thread = db.get(MailThread, int(row.thread_id or 0)) if int(row.thread_id or 0) > 0 else None
        message = db.get(EmailMessage, int(row.mail_message_id or 0)) if int(row.mail_message_id or 0) > 0 else None
        if message is None:
            message = EmailMessage(
                account_id=int(account.id),
                thread_id=int(thread.id) if thread else None,
                folder="OUTBOX",
                uid=f"outbox:{int(row.id)}",
                direction="out",
                subject=row.subject or None,
                body_text=row.body_text or None,
                body_html=row.body_html or None,
                from_text=account.email,
                from_email=account.email,
                to_emails=row.to_email,
                cc_emails=row.cc_emails,
                bcc_emails=row.bcc_emails,
                assignment_status="assigned" if int(row.master_customer_id or 0) > 0 or int(row.case_id or 0) > 0 else "unassigned",
                master_customer_id=int(row.master_customer_id or 0) or None,
                case_id=int(row.case_id or 0) or None,
                fetched_at=_utcnow_naive(),
            )
            db.add(message)
            db.flush()
            row.mail_message_id = int(message.id)
        last_header = (
            db.query(EmailMessage)
            .filter(EmailMessage.thread_id == int(thread.id or 0), EmailMessage.message_id_header.is_not(None))
            .order_by(func.coalesce(EmailMessage.sent_at, EmailMessage.received_at, EmailMessage.fetched_at).desc(), EmailMessage.id.desc())
            .first()
            if thread
            else None
        )
        message_id_header = _normalize_message_id_header(message.message_id_header or make_msgid())
        try:
            client = _smtp_client(account)
            mime = MimeEmailMessage()
            mime["Subject"] = row.subject or ""
            mime["From"] = account.email
            mime["To"] = row.to_email or ""
            if row.cc_emails:
                mime["Cc"] = row.cc_emails
            if message_id_header:
                mime["Message-ID"] = f"<{message_id_header}>"
            if last_header and str(last_header.message_id_header or "").strip():
                last_message_id = _normalize_message_id_header(last_header.message_id_header)
                if last_message_id:
                    mime["In-Reply-To"] = f"<{last_message_id}>"
                refs = " ".join(
                    f"<{value}>"
                    for value in [
                        *[
                            _normalize_message_id_header(part)
                            for part in re.split(r"[\\s,]+", str(last_header.references_header or "").strip())
                            if str(part or "").strip()
                        ],
                        last_message_id,
                    ]
                    if value
                )
                if refs:
                    mime["References"] = refs
            if row.body_html:
                mime.set_content(row.body_text or "")
                mime.add_alternative(row.body_html, subtype="html")
            else:
                mime.set_content(row.body_text or "")
            recipients = [addr for _, addr in getaddresses([row.to_email or "", row.cc_emails or "", row.bcc_emails or ""]) if str(addr or "").strip()]
            client.send_message(mime, to_addrs=recipients or None)
            try:
                client.quit()
            except Exception:
                pass
            row.status = "sent"
            row.sent_at = _utcnow_naive()
            row.last_error = None
            message.account_id = int(account.id)
            message.direction = "out"
            message.folder = "OUTBOX"
            message.message_id_header = message_id_header
            message.in_reply_to = _normalize_message_id_header(last_header.message_id_header if last_header else None)
            message.references_header = " ".join(
                [
                    value
                    for value in [
                        _normalize_message_id_header(part)
                        for part in re.split(r"[\\s,]+", str(mime.get("References") or "").strip())
                        if str(part or "").strip()
                    ]
                    if value
                ]
            ) or None
            message.from_text = account.email
            message.from_email = account.email
            message.to_emails = row.to_email
            message.cc_emails = row.cc_emails
            message.bcc_emails = row.bcc_emails
            message.subject = row.subject or None
            message.body_text = row.body_text or None
            message.body_html = row.body_html or None
            message.sent_at = row.sent_at
            message.assignment_status = "assigned" if int(message.master_customer_id or 0) > 0 or int(message.case_id or 0) > 0 else message.assignment_status
            message.fetched_at = row.sent_at or message.fetched_at or _utcnow_naive()
            db.add(message)
            if thread:
                thread.last_message_at = row.sent_at
                db.add(thread)
                _timeline_event(
                    db,
                    thread=thread,
                    message=message,
                    title=f"E-Mail gesendet: {message.subject or '(ohne Betreff)'}",
                    body=f"An: {message.to_emails or '-'}",
                    event_type="mail_out",
                )
            db.add(row)
            sent += 1
        except Exception as exc:
            row.status = "error"
            row.attempts = int(row.attempts or 0) + 1
            row.last_error = friendly_mail_error(exc)
            db.add(row)
            failed += 1
    return {"processed": len(rows), "sent": sent, "failed": failed}


def fetch_inbox_once(db: Session, account_id: int, limit: int = 50) -> dict[str, int]:
    account = db.get(EmailAccount, int(account_id))
    if not account or not account.enabled:
        raise ValueError("E-Mail-Konto nicht gefunden oder deaktiviert.")

    client = None
    created = 0
    scanned = 0
    try:
        client = _imap_client(account)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise ValueError("INBOX konnte nicht geöffnet werden.")

        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise ValueError("INBOX konnte nicht gelesen werden.")
        raw_ids = (data[0] or b"").split() if data and data[0] else []
        wanted = raw_ids[-max(1, int(limit)) :]
        scanned = len(wanted)

        for uid_bytes in wanted:
            uid = uid_bytes.decode("utf-8", errors="ignore")
            exists = (
                db.query(EmailMessage)
                .filter(EmailMessage.account_id == account.id, EmailMessage.folder == "INBOX", EmailMessage.uid == uid)
                .count()
            )
            if exists:
                continue
            st, msg_data = client.uid("fetch", uid, "(RFC822)")
            if st != "OK" or not msg_data:
                continue
            raw_msg = b""
            for item in msg_data:
                if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                    raw_msg = bytes(item[1])
                    break
            if not raw_msg:
                continue

            parsed = email.message_from_bytes(raw_msg)
            subject = _decode_header_value(parsed.get("Subject"))
            from_text = _decode_header_value(parsed.get("From"))
            _, from_email = parseaddr(from_text or parsed.get("From") or "")
            date_text = _decode_header_value(parsed.get("Date"))
            body_text = _extract_plain_text(parsed).strip()
            body_html = _extract_html_text(parsed).strip()
            snippet = " ".join((body_text or "").split())[:240]
            to_emails = _addresses_csv([str(parsed.get("To") or "")])
            cc_emails = _addresses_csv([str(parsed.get("Cc") or "")])
            message_id_header = _normalize_message_id_header(_decode_header_value(parsed.get("Message-ID") or ""))
            in_reply_to = _normalize_message_id_header(_decode_header_value(parsed.get("In-Reply-To") or ""))
            references_header = " ".join(
                [
                    value
                    for value in [
                        _normalize_message_id_header(part)
                        for part in re.split(r"[\\s,]+", _decode_header_value(parsed.get("References") or "").strip())
                        if str(part or "").strip()
                    ]
                    if value
                ]
            ) or None
            attachment_rows = _extract_attachments(parsed)
            suggestion = suggest_assignments(
                db,
                from_email=from_email or None,
                to_emails=to_emails,
                cc_emails=cc_emails,
                subject=subject,
                body_text=body_text,
                in_reply_to=in_reply_to,
                references_header=references_header,
                attachment_names=[str(item.get("filename") or "") for item in attachment_rows],
            )
            customer_ids = list(suggestion.get("customer_ids") or [])
            case_ids = list(suggestion.get("case_ids") or [])
            received_at = _parse_received_datetime(date_text) or _utcnow_naive()
            thread = _resolve_mail_thread(
                db,
                subject=subject,
                header_thread_id=int(suggestion.get("thread_id") or 0) or None,
                customer_id=customer_ids[0] if len(customer_ids) == 1 else None,
                case_id=case_ids[0] if len(case_ids) == 1 else None,
                message_dt=received_at,
            )

            row = EmailMessage(
                account_id=account.id,
                thread_id=int(thread.id),
                folder="INBOX",
                uid=uid,
                direction="in",
                message_id_header=message_id_header,
                in_reply_to=in_reply_to,
                references_header=references_header,
                from_text=from_text or None,
                from_email=(from_email or "").strip() or None,
                to_emails=to_emails,
                cc_emails=cc_emails,
                subject=subject or None,
                date_text=date_text or None,
                snippet=snippet or None,
                body_text=(body_text[:15000] if body_text else None),
                body_html=(body_html[:30000] if body_html else None),
                received_at=received_at,
                fetched_at=_utcnow_naive(),
            )
            _apply_assignment(row, thread, customer_ids=customer_ids, case_ids=case_ids, status=str(suggestion.get("status") or "unassigned"))
            db.add(row)
            db.flush()
            for item in attachment_rows:
                rel_path = _save_attachment_file(int(row.id), str(item.get("filename") or "anhang.bin"), bytes(item.get("payload") or b""))
                db.add(
                    MailAttachment(
                        mail_message_id=int(row.id),
                        filename=_safe_mail_filename(str(item.get("filename") or "anhang.bin")),
                        mime_type=str(item.get("mime_type") or "application/octet-stream"),
                        file_path=rel_path,
                        created_at=_utcnow_naive(),
                    )
                )
            thread.last_message_at = received_at
            db.add(thread)
            reason_text = " | ".join(str(value) for value in (suggestion.get("reasons") or []) if str(value or "").strip())
            _timeline_event(
                db,
                thread=thread,
                message=row,
                title=f"E-Mail eingegangen: {row.subject or '(ohne Betreff)'}",
                body=f"Von: {row.from_email or row.from_text or '-'}" + (f"\nZuordnung: {reason_text}" if reason_text else ""),
                event_type="mail_in",
            )
            created += 1
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass
    return {"scanned": scanned, "created": created}
