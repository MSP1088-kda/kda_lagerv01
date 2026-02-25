from __future__ import annotations

import datetime as dt
import email
from email.header import decode_header
from email.message import EmailMessage as MimeEmailMessage
import imaplib
import smtplib
import socket
import ssl
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import EmailAccount, EmailMessage, EmailOutbox
from ..utils import get_fernet


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


def _smtp_client(account: EmailAccount):
    if not account.smtp_host or not account.smtp_port:
        raise ValueError("SMTP-Host/Port fehlen.")
    timeout = 12
    if bool(account.smtp_tls):
        client = smtplib.SMTP(account.smtp_host, int(account.smtp_port), timeout=timeout)
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
    else:
        client = smtplib.SMTP(account.smtp_host, int(account.smtp_port), timeout=timeout)
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
        try:
            send_email_via_account(account, row.to_email, row.subject or "", row.body_text or "")
            row.status = "sent"
            row.sent_at = dt.datetime.utcnow().replace(tzinfo=None)
            row.last_error = None
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
            date_text = _decode_header_value(parsed.get("Date"))
            body_text = _extract_plain_text(parsed).strip()
            snippet = " ".join((body_text or "").split())[:240]

            db.add(
                EmailMessage(
                    account_id=account.id,
                    folder="INBOX",
                    uid=uid,
                    from_text=from_text or None,
                    subject=subject or None,
                    date_text=date_text or None,
                    snippet=snippet or None,
                    body_text=(body_text[:15000] if body_text else None),
                )
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
