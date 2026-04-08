"""Gmail feedback fetcher via IMAP (app password)."""

import base64
import email
import imaplib
import re
from datetime import timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

import requests


def fetch_gmail_messages(email_address, app_password, query="", count=80, folder="INBOX"):
    """Fetch emails from Gmail and normalize them into feedback items."""
    address = (email_address or "").strip()
    secret = (app_password or "").strip()
    mailbox = (folder or "INBOX").strip() or "INBOX"
    target_count = max(1, int(count or 80))

    if not address or not secret:
        print("Gmail email/app password missing.")
        return []

    print(
        f"Fetching up to {target_count} Gmail messages from '{mailbox}'"
        + (f" with query '{query}'" if query else "")
        + "..."
    )

    mail = None
    items = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(address, secret)
        select_status, _ = mail.select(mailbox, readonly=True)
        if select_status != "OK":
            print(f"Unable to open Gmail folder: {mailbox}")
            return []

        uids = _search_uids(mail, query=query)
        if not uids:
            print("No Gmail messages found for the given query.")
            return []

        # Use newest first.
        for uid in reversed(uids[-target_count:]):
            item = _fetch_one_message(mail, uid, address=address, mailbox=mailbox)
            if item:
                items.append(item)

    except Exception as e:
        print(f"Gmail fetch failed: {e}")
        return []
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass

    items = [i for i in items if i.get("text") and len(i["text"]) > 4]
    print(f"Fetched {len(items)} Gmail messages")
    return items


def fetch_gmail_messages_oauth(access_token, query="", count=80, folder="INBOX"):
    """Fetch Gmail messages via Gmail API using OAuth access token."""
    token = (access_token or "").strip()
    if not token:
        print("Missing Gmail OAuth access token.")
        return []

    target_count = max(1, int(count or 80))
    effective_query = _build_gmail_query(query=query, folder=folder)
    print(
        f"Fetching up to {target_count} Gmail messages via OAuth"
        + (f" with query '{effective_query}'" if effective_query else "")
        + "..."
    )

    headers = {"Authorization": f"Bearer {token}"}
    items = []
    page_token = None
    pages = 0
    max_pages = 10

    try:
        while len(items) < target_count and pages < max_pages:
            params = {
                "maxResults": min(100, target_count - len(items)),
                "q": effective_query
            }
            if page_token:
                params["pageToken"] = page_token

            resp = requests.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params=params,
                timeout=20
            )
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                msg = _extract_gmail_api_error(data) or f"HTTP {resp.status_code}"
                print(f"Gmail API list failed: {msg}")
                return []

            messages = data.get("messages", [])
            page_token = data.get("nextPageToken")
            pages += 1

            if not messages:
                break

            for m in messages:
                msg_id = m.get("id")
                if not msg_id:
                    continue
                item = _fetch_one_message_oauth(msg_id=msg_id, headers=headers, folder=folder)
                if item:
                    items.append(item)
                if len(items) >= target_count:
                    break

            if not page_token:
                break

    except Exception as e:
        print(f"Gmail OAuth fetch failed: {e}")
        return []

    items = [i for i in items if i.get("text") and len(i["text"]) > 4]
    print(f"Fetched {len(items)} Gmail OAuth messages")
    return items


def _search_uids(mail, query=""):
    query = (query or "").strip()

    if query:
        try:
            status, data = mail.uid("search", None, "X-GM-RAW", f'"{query}"')
            if status == "OK" and data and data[0]:
                return data[0].split()
        except Exception:
            pass

        # Fallback to broad text search if X-GM-RAW is unavailable.
        try:
            status, data = mail.uid("search", None, "TEXT", f'"{query}"')
            if status == "OK" and data and data[0]:
                return data[0].split()
        except Exception:
            pass

    status, data = mail.uid("search", None, "ALL")
    if status != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def _fetch_one_message(mail, uid, address, mailbox):
    fetch_status, msg_data = mail.uid("fetch", uid, "(RFC822)")
    if fetch_status != "OK":
        return None

    raw_bytes = None
    for chunk in msg_data:
        if isinstance(chunk, tuple) and len(chunk) >= 2 and isinstance(chunk[1], (bytes, bytearray)):
            raw_bytes = chunk[1]
            break
    if not raw_bytes:
        return None

    msg = email.message_from_bytes(raw_bytes)
    subject = _decode_header_text(msg.get("Subject", ""))
    from_header = _decode_header_text(msg.get("From", ""))
    from_name, from_email = parseaddr(from_header)
    author = from_name or from_email or "unknown"

    body = _extract_body_text(msg)
    text = f"{subject}. {body}".strip(" .")
    if not text:
        return None

    uid_str = uid.decode("utf-8") if isinstance(uid, (bytes, bytearray)) else str(uid)
    date_iso = _to_iso_datetime(msg.get("Date", ""))

    return {
        "id": f"gm_{uid_str}",
        "source": "gmail",
        "text": text,
        "author": author,
        "date": date_iso,
        "rating": None,
        "metadata": {
            "gmail_account": address,
            "folder": mailbox,
            "from": from_header,
            "to": _decode_header_text(msg.get("To", "")),
            "subject": subject,
            "message_id": msg.get("Message-ID", "")
        }
    }


def _fetch_one_message_oauth(msg_id, headers, folder):
    resp = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
        headers=headers,
        params={"format": "full"},
        timeout=20
    )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        return None

    payload = data.get("payload", {}) or {}
    headers_map = _gmail_header_map(payload.get("headers", []) or [])

    subject = headers_map.get("subject", "")
    from_header = headers_map.get("from", "")
    to_header = headers_map.get("to", "")
    date_iso = _to_iso_datetime(headers_map.get("date", ""))
    from_name, from_email = parseaddr(from_header)
    author = from_name or from_email or "unknown"

    body = _extract_body_from_payload(payload)
    snippet = _clean_whitespace(data.get("snippet", ""))
    text = f"{subject}. {body or snippet}".strip(" .")
    if not text:
        return None

    return {
        "id": f"gm_{msg_id}",
        "source": "gmail",
        "text": text,
        "author": author,
        "date": date_iso,
        "rating": None,
        "metadata": {
            "gmail_account": "oauth_connected",
            "folder": folder,
            "from": from_header,
            "to": to_header,
            "subject": subject,
            "message_id": headers_map.get("message-id", ""),
            "thread_id": data.get("threadId", ""),
            "gmail_message_id": msg_id
        }
    }


def _extract_body_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = (part.get_content_type() or "").lower()
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            if content_type in {"text/plain", "text/html"}:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="ignore")
                if content_type == "text/html":
                    text = _strip_html(text)
                text = _clean_whitespace(text)
                if text:
                    return text
        return ""

    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="ignore")
    if (msg.get_content_type() or "").lower() == "text/html":
        text = _strip_html(text)
    return _clean_whitespace(text)


def _decode_header_text(value):
    if not value:
        return ""
    out = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            out.append(chunk.decode(charset or "utf-8", errors="ignore"))
        else:
            out.append(str(chunk))
    return "".join(out).strip()


def _strip_html(value):
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return text


def _clean_whitespace(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def _to_iso_datetime(raw_date):
    if not raw_date:
        return ""
    try:
        dt = parsedate_to_datetime(raw_date)
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


def _build_gmail_query(query="", folder="INBOX"):
    q = (query or "").strip()
    f = (folder or "INBOX").strip()
    base = ""

    if f and f.upper() != "INBOX":
        base = f"label:{f}"
    elif f:
        base = "in:inbox"

    if base and q:
        return f"{base} ({q})"
    return base or q


def _extract_gmail_api_error(data):
    if not isinstance(data, dict):
        return ""
    err = data.get("error", {})
    if isinstance(err, dict):
        if "message" in err:
            return str(err.get("message", ""))
        if "errors" in err and isinstance(err["errors"], list) and err["errors"]:
            first = err["errors"][0]
            if isinstance(first, dict):
                return str(first.get("message", ""))
    return ""


def _gmail_header_map(headers):
    out = {}
    for h in headers:
        if isinstance(h, dict):
            name = (h.get("name") or "").lower().strip()
            val = h.get("value") or ""
            if name:
                out[name] = _decode_header_text(val)
    return out


def _extract_body_from_payload(payload):
    if not isinstance(payload, dict):
        return ""

    # Prefer explicit plain text body first.
    mime = (payload.get("mimeType") or "").lower()
    body_data = ((payload.get("body") or {}).get("data") or "").strip()
    if body_data and mime == "text/plain":
        return _clean_whitespace(_decode_b64url(body_data))

    parts = payload.get("parts") or []
    for part in parts:
        text = _extract_body_from_payload(part)
        if text:
            return text

    # Fallback to html body conversion.
    if body_data and mime == "text/html":
        return _clean_whitespace(_strip_html(_decode_b64url(body_data)))

    return ""


def _decode_b64url(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    pad = "=" * ((4 - len(raw) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("utf-8"))
        return unescape(decoded.decode("utf-8", errors="ignore"))
    except Exception:
        return ""
