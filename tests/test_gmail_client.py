"""Unit tests — gmail_client (body extraction + normalization, no network).

OAuth flow + API calls nie są testowane tu (wymaga mock Google API lub real token).
Skupiamy się na pure logic: body extraction z multipart MIME + Polish UTF-8 normalization.
"""
from __future__ import annotations

import base64

from lib.gmail_client import (
    _count_attachments,
    _decode_header_value,
    _extract_body_text,
    _normalize_message,
    _normalize_polish_utf8,
    _parse_date_iso,
    _strip_html_tags,
)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def test_extract_body_text_plain_only() -> None:
    payload = {
        "mimeType": "text/plain",
        "body": {"data": _b64("Cześć, to jest test.")},
    }
    assert _extract_body_text(payload) == "Cześć, to jest test."


def test_extract_body_prefers_text_plain_over_html() -> None:
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>HTML version</p>")}},
            {"mimeType": "text/plain", "body": {"data": _b64("Plain version")}},
        ],
    }
    assert _extract_body_text(payload) == "Plain version"


def test_extract_body_falls_back_to_html_when_no_plain() -> None:
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>Hello <b>world</b></p>")}},
        ],
    }
    result = _extract_body_text(payload)
    assert "Hello" in result
    assert "world" in result
    assert "<" not in result  # HTML stripped


def test_extract_body_nested_multipart() -> None:
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("Nested plain text")}},
                ],
            },
            {"mimeType": "application/pdf", "filename": "attachment.pdf",
             "body": {"attachmentId": "att-1"}},
        ],
    }
    assert _extract_body_text(payload) == "Nested plain text"


def test_strip_html_removes_script_and_style() -> None:
    html = "<script>alert('xss')</script><p>Visible</p><style>body{}</style>"
    result = _strip_html_tags(html)
    assert "alert" not in result
    assert "body{}" not in result
    assert "Visible" in result


def test_normalize_polish_utf8_handles_bom() -> None:
    text_with_bom = "﻿Cześć"
    assert _normalize_polish_utf8(text_with_bom) == "Cześć"


def test_normalize_polish_utf8_nfc_normalization() -> None:
    # NFD decomposed ś vs NFC precomposed ś
    decomposed = "światłowód"
    result = _normalize_polish_utf8(decomposed)
    assert "ś" in result


def test_decode_header_value_encoded_polish() -> None:
    # "Cześć" UTF-8: C=43, z=7A, e=65, ś=C5 9B, ć=C4 87
    encoded = "=?utf-8?Q?Cze=C5=9B=C4=87?="
    assert _decode_header_value(encoded) == "Cześć"


def test_decode_header_value_plain() -> None:
    assert _decode_header_value("plain text") == "plain text"


def test_decode_header_value_empty() -> None:
    assert _decode_header_value("") == ""


def test_parse_date_iso_standard_rfc822() -> None:
    raw = "Wed, 24 Apr 2026 17:32:15 +0200"
    result = _parse_date_iso(raw)
    assert "2026-04-24" in result
    assert "17:32" in result


def test_parse_date_iso_empty_returns_empty() -> None:
    assert _parse_date_iso("") == ""


def test_count_attachments_flat() -> None:
    payload = {
        "parts": [
            {"filename": "doc.pdf", "body": {"attachmentId": "a1"}},
            {"filename": "", "body": {}},  # not attachment
        ],
    }
    assert _count_attachments(payload) == 1


def test_count_attachments_nested() -> None:
    payload = {
        "parts": [
            {
                "parts": [
                    {"filename": "photo.jpg", "body": {"attachmentId": "a1"}},
                ],
            },
            {"filename": "doc.pdf", "body": {"attachmentId": "a2"}},
        ],
    }
    assert _count_attachments(payload) == 2


def test_normalize_message_end_to_end() -> None:
    msg = {
        "id": "msg-123",
        "threadId": "thread-456",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Jan Kowalski <jan.kowalski@example.com>"},
                {"name": "To", "value": "tata@example.com"},
                {"name": "Subject", "value": "Raport 2026-04-24"},
                {"name": "Date", "value": "Wed, 24 Apr 2026 17:32:15 +0200"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64("Treść maila.")},
        },
    }
    result = _normalize_message(msg)
    assert result["id"] == "msg-123"
    assert result["from"] == "jan.kowalski@example.com"
    assert result["from_name"] == "Jan Kowalski"
    assert result["subject"] == "Raport 2026-04-24"
    assert result["body_text"] == "Treść maila."
    assert result["labels"] == ["INBOX", "UNREAD"]
    assert "2026-04-24" in result["received_at_iso"]
