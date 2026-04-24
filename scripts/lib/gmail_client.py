"""Gmail native client — OAuth flow + list + get + body extraction.

Per D2 Phase 1 override (MAXIMISEART-Dad CLAUDE.md): native google-api-python-client
(NIE MCP) — wymagane dla Task Scheduler (standalone, zero Claude session dependency).

Wzór strukturalny: MAXIMISEART-SEO/seo_client_data_sync/oauth_flow.py
Uproszczenie vs SEO version: single-user token (tata), brak per-klient AES vault.
"""
from __future__ import annotations

import base64
import email.utils
import json
import time
import unicodedata
from email.header import decode_header
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class OAuthExpiredError(Exception):
    """Refresh token cofnięty/wygasł — wymagana ponowna autoryzacja."""


class ClientSecretMissingError(Exception):
    """Brak client_secret.json — download z Google Cloud Console."""


def run_oauth_flow(client_secret_path: Path, token_path: Path, port: int = 0) -> Credentials:
    """Interactive OAuth — otwiera browser, lokalny serwer catchuje callback.

    Phase 1: Maks runs this once na swoim kompie (init_wizard --phase-1-setup).
    Phase 5: tata runs this once na swoim kompie (init_wizard u taty).
    """
    if not client_secret_path.exists():
        raise ClientSecretMissingError(
            f"Brak {client_secret_path}. Pobierz OAuth client (Desktop) "
            f"z Google Cloud Console → APIs & Services → Credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path),
        scopes=GMAIL_SCOPES,
    )
    creds = flow.run_local_server(port=port, prompt="consent")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def load_or_refresh_credentials(token_path: Path) -> Credentials:
    """Load cached token, refresh if expired, return valid Credentials.

    Raises OAuthExpiredError jeśli refresh_token cofnięty (wymagana re-auth).
    """
    if not token_path.exists():
        raise OAuthExpiredError(
            f"Token nie istnieje: {token_path}. Uruchom init_wizard --phase-1-setup."
        )

    creds_info = json.loads(token_path.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(creds_info)

    if creds.valid:
        return creds

    if not creds.refresh_token:
        raise OAuthExpiredError(
            "Brak refresh_token. Uruchom init_wizard --phase-1-setup ponownie."
        )

    try:
        creds.refresh(Request())
    except Exception as e:
        if "invalid_grant" in str(e).lower():
            raise OAuthExpiredError(
                "Refresh token cofnięty lub wygasł. Uruchom init_wizard --phase-1-setup."
            ) from e
        raise

    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def harvest_emails(
    token_path: Path,
    query: str = "newer_than:1d",
    max_results: int = 500,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Harvest normalized emails matching query.

    Args:
        token_path: Path do oauth-token.json
        query: Gmail search query (default last 24h). Phase 1 test: '[DAD-TEST] newer_than:1d'
        max_results: Cap na ilość emaili (safety)
        max_retries: Rate limit exponential backoff attempts

    Returns:
        List of {id, thread_id, from, from_name, to, subject, body_text,
                 received_at_iso, attachments_count, labels}

    Raises:
        OAuthExpiredError: refresh failed
    """
    creds = load_or_refresh_credentials(token_path)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    message_ids = _list_message_ids_with_retry(service, query, max_results, max_retries)
    emails: list[dict[str, Any]] = []
    for msg_id in message_ids:
        full = _get_message_with_retry(service, msg_id, max_retries)
        if full is None:
            continue
        emails.append(_normalize_message(full))
    return emails


def _list_message_ids_with_retry(
    service, query: str, max_results: int, max_retries: int
) -> list[str]:
    """List message IDs with exponential backoff on rate limit."""
    attempt = 0
    while attempt <= max_retries:
        try:
            result = service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            return [msg["id"] for msg in result.get("messages", [])]
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries:
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            raise
    return []


def _get_message_with_retry(service, msg_id: str, max_retries: int) -> dict | None:
    attempt = 0
    while attempt <= max_retries:
        try:
            return service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries:
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            return None
    return None


def _normalize_message(msg: dict) -> dict[str, Any]:
    """Convert Gmail API response to normalized dict."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    from_raw = headers.get("from", "")
    from_name, from_email = email.utils.parseaddr(from_raw)

    subject = _decode_header_value(headers.get("subject", ""))
    from_name_decoded = _decode_header_value(from_name)

    received_at_iso = _parse_date_iso(headers.get("date", ""))
    body_text = _extract_body_text(msg.get("payload", {}))
    attachments_count = _count_attachments(msg.get("payload", {}))

    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "from": from_email.lower(),
        "from_name": from_name_decoded,
        "to": headers.get("to", "").lower(),
        "subject": subject,
        "body_text": _normalize_polish_utf8(body_text),
        "received_at_iso": received_at_iso,
        "attachments_count": attachments_count,
        "labels": msg.get("labelIds", []),
    }


def _decode_header_value(raw: str) -> str:
    if not raw:
        return ""
    decoded_parts = decode_header(raw)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _parse_date_iso(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return dt.isoformat()
    except (TypeError, ValueError):
        return raw


def _extract_body_text(payload: dict) -> str:
    """Extract body text prefering text/plain, fallback text/html stripped."""
    if not payload:
        return ""

    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    parts = payload.get("parts", [])

    if mime_type == "text/plain":
        return _decode_body_data(body)

    if mime_type == "text/html":
        html = _decode_body_data(body)
        return _strip_html_tags(html)

    if parts:
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = _decode_body_data(part.get("body", {}))
                if data:
                    return data
        for part in parts:
            if part.get("mimeType") == "text/html":
                data = _decode_body_data(part.get("body", {}))
                if data:
                    return _strip_html_tags(data)
        for part in parts:
            text = _extract_body_text(part)
            if text:
                return text

    return ""


def _decode_body_data(body: dict) -> str:
    data = body.get("data", "")
    if not data:
        return ""
    try:
        decoded_bytes = base64.urlsafe_b64decode(data + "===")
        return decoded_bytes.decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _strip_html_tags(html: str) -> str:
    import re
    text = re.sub(r"<(script|style).*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _count_attachments(payload: dict) -> int:
    count = 0
    parts = payload.get("parts", [])
    for part in parts:
        filename = part.get("filename", "")
        if filename and part.get("body", {}).get("attachmentId"):
            count += 1
        count += _count_attachments(part)
    return count


def _normalize_polish_utf8(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    if normalized.startswith("﻿"):
        normalized = normalized[1:]
    return normalized
