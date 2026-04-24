"""Unit tests — obsidian_writer (pure Python markdown + dedup)."""
from __future__ import annotations

from pathlib import Path

from lib.obsidian_writer import append_daily_email_log, ensure_employee_folder


def _sample_employee() -> dict:
    return {
        "slug": "jan-kowalski",
        "name": "Jan Kowalski",
        "email": "jan.kowalski@example.com",
        "aliases": ["JK"],
        "kody_prac_typowe": [1, 2],
    }


def _sample_email(email_id: str = "msg-001") -> dict:
    return {
        "id": email_id,
        "thread_id": "t1",
        "from": "jan.kowalski@example.com",
        "from_name": "Jan Kowalski",
        "to": "tata@example.com",
        "subject": "Raport dzienny 2026-04-24",
        "body_text": "Cześć,\n\nZrobiłem 3x FTTH na Krańcowej 12.\n\nJan",
        "received_at_iso": "2026-04-24T17:32:15+02:00",
        "attachments_count": 0,
        "labels": ["INBOX"],
    }


def test_ensure_folder_creates_profil_stub(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    folder = ensure_employee_folder(vault, "jan-kowalski", _sample_employee())
    assert folder.exists()
    profil = folder / "_profil.md"
    assert profil.exists()
    content = profil.read_text(encoding="utf-8")
    assert "Jan Kowalski" in content
    assert "jan.kowalski@example.com" in content
    assert "Key Patterns" in content


def test_append_first_email_creates_daily_log(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ensure_employee_folder(vault, "jan-kowalski", _sample_employee())
    appended = append_daily_email_log(
        vault, "jan-kowalski", "2026-04-24", _sample_employee(), _sample_email()
    )
    assert appended is True
    daily = vault / "pracownicy" / "jan-kowalski" / "2026-04-24.md"
    assert daily.exists()
    content = daily.read_text(encoding="utf-8")
    assert "# 2026-04-24 — Jan Kowalski" in content
    assert "emails_count: 1" in content
    assert "Raport dzienny" in content
    assert "msg-001" in content
    assert "<!-- email-id: msg-001 -->" in content


def test_duplicate_email_id_returns_false_no_append(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ensure_employee_folder(vault, "jan-kowalski", _sample_employee())
    email = _sample_email("msg-001")

    first = append_daily_email_log(vault, "jan-kowalski", "2026-04-24", _sample_employee(), email)
    second = append_daily_email_log(vault, "jan-kowalski", "2026-04-24", _sample_employee(), email)

    assert first is True
    assert second is False  # deduped

    daily = vault / "pracownicy" / "jan-kowalski" / "2026-04-24.md"
    content = daily.read_text(encoding="utf-8")
    # marker should appear exactly once (dedup); raw ID appears in marker + Meta line = 2×
    assert content.count("<!-- email-id: msg-001 -->") == 1
    assert "emails_count: 1" in content


def test_second_unique_email_increments_count(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ensure_employee_folder(vault, "jan-kowalski", _sample_employee())
    email1 = _sample_email("msg-001")
    email2 = _sample_email("msg-002")

    append_daily_email_log(vault, "jan-kowalski", "2026-04-24", _sample_employee(), email1)
    append_daily_email_log(vault, "jan-kowalski", "2026-04-24", _sample_employee(), email2)

    daily = vault / "pracownicy" / "jan-kowalski" / "2026-04-24.md"
    content = daily.read_text(encoding="utf-8")
    assert "emails_count: 2" in content
    assert "msg-001" in content
    assert "msg-002" in content
    assert "## Email 1 —" in content
    assert "## Email 2 —" in content


def test_polish_characters_preserved(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ensure_employee_folder(vault, "anna", {"slug": "anna", "name": "Anna Wiśniewska"})
    email = _sample_email("msg-pl")
    email["body_text"] = "Cześć, zrobiłem mufę na ul. Żółtej 3. Ścieżki są już przepuszczone."
    email["subject"] = "Raport — ul. Żółta 3 (światłowód)"

    append_daily_email_log(
        vault, "anna", "2026-04-24", {"slug": "anna", "name": "Anna Wiśniewska"}, email
    )

    daily = vault / "pracownicy" / "anna" / "2026-04-24.md"
    content = daily.read_text(encoding="utf-8")
    assert "Żółtej 3" in content
    assert "Ścieżki" in content
    assert "Wiśniewska" in content


def test_empty_body_shows_placeholder(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ensure_employee_folder(vault, "jan-kowalski", _sample_employee())
    email = _sample_email("msg-empty")
    email["body_text"] = ""

    append_daily_email_log(vault, "jan-kowalski", "2026-04-24", _sample_employee(), email)

    daily = vault / "pracownicy" / "jan-kowalski" / "2026-04-24.md"
    content = daily.read_text(encoding="utf-8")
    assert "_(pusta treść)_" in content
