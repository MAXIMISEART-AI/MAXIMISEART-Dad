"""Pure Python Obsidian writer — markdown + YAML frontmatter + idempotent append.

Phase 1 override: NIE używamy obsidian-cli (wymaga app running). Pure Python pisze
.md bezpośrednio. Obsidian wykrywa zmiany przy otwarciu vault.

Rule #1 Floor Never Drops: append-only, dedup via email.id.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def ensure_employee_folder(vault_path: Path, slug: str, employee: dict | None = None) -> Path:
    """Create vault/pracownicy/{slug}/ z _profil.md stub jeśli brak.

    Args:
        vault_path: Root vault path (runtime/vault/)
        slug: Employee kebab-case slug
        employee: Optional employees.yaml dict (dla _profil.md frontmatter)

    Returns:
        Path do folderu pracownika.
    """
    folder = vault_path / "pracownicy" / slug
    folder.mkdir(parents=True, exist_ok=True)

    profil = folder / "_profil.md"
    if not profil.exists():
        profil.write_text(_render_profil_stub(slug, employee), encoding="utf-8")

    return folder


def append_daily_email_log(
    vault_path: Path, slug: str, date: str, employee: dict, email: dict[str, Any]
) -> bool:
    """Append single email entry to vault/pracownicy/{slug}/YYYY-MM-DD.md.

    Idempotent: dedup via email.id w istniejących entries (comment marker).
    Floor Never Drops: append-only, nigdy nie nadpisuje.

    Returns:
        True jeśli email dopisany, False jeśli już był (deduped).
    """
    folder = vault_path / "pracownicy" / slug
    folder.mkdir(parents=True, exist_ok=True)
    daily_log = folder / f"{date}.md"

    email_id = email.get("id", "")
    marker = f"<!-- email-id: {email_id} -->"

    if daily_log.exists():
        existing = daily_log.read_text(encoding="utf-8")
        if marker in existing:
            return False
        current_count = _parse_emails_count(existing)
        new_count = current_count + 1
        updated = _bump_emails_count_frontmatter(existing, new_count)
        updated += "\n" + _render_email_entry(email, new_count, marker) + "\n"
        daily_log.write_text(updated, encoding="utf-8")
        return True

    content = _render_daily_log_header(date, employee, emails_count=1)
    content += "\n" + _render_email_entry(email, 1, marker) + "\n"
    daily_log.write_text(content, encoding="utf-8")
    return True


def _render_daily_log_header(date: str, employee: dict, emails_count: int) -> str:
    frontmatter = {
        "date": date,
        "employee_slug": employee.get("slug", ""),
        "employee_name": employee.get("name", ""),
        "emails_count": emails_count,
        "generated": datetime.now().isoformat(timespec="seconds"),
    }
    fm_yaml = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    title = f"{date} — {employee.get('name', employee.get('slug', ''))}"
    return f"---\n{fm_yaml}\n---\n\n# {title}\n"


def _render_email_entry(email: dict[str, Any], index: int, marker: str) -> str:
    received_iso = email.get("received_at_iso", "")
    time_short = _extract_time_hhmm(received_iso)
    subject = email.get("subject", "(brak tematu)")
    body = email.get("body_text", "").strip() or "_(pusta treść)_"
    from_email = email.get("from", "")
    msg_id = email.get("id", "")
    attachments = email.get("attachments_count", 0)

    lines = [
        marker,
        f"## Email {index} — {time_short} — \"{subject}\"",
        "",
        body,
        "",
        f"**Meta:** from={from_email}, id={msg_id}, attachments={attachments}",
        "",
        "---",
    ]
    return "\n".join(lines)


def _extract_time_hhmm(iso: str) -> str:
    if not iso:
        return "??:??"
    match = re.search(r"T(\d{2}:\d{2})", iso)
    return match.group(1) if match else "??:??"


def _parse_emails_count(content: str) -> int:
    match = re.search(r"^emails_count:\s*(\d+)", content, flags=re.MULTILINE)
    return int(match.group(1)) if match else 0


def _bump_emails_count_frontmatter(content: str, new_count: int) -> str:
    return re.sub(
        r"^emails_count:\s*\d+",
        f"emails_count: {new_count}",
        content,
        count=1,
        flags=re.MULTILINE,
    )


def _render_profil_stub(slug: str, employee: dict | None) -> str:
    emp = employee or {}
    frontmatter = {
        "aliases": emp.get("aliases", []) or [emp.get("name", slug)],
        "tags": ["pracownik", "fiber-team"],
        "employee_id": slug,
        "email": emp.get("email", ""),
        "kody_prac_typowe": emp.get("kody_prac_typowe", []),
        "styl_pisania": emp.get("styl_pisania", []),
        "errors_known": [],
        "created": datetime.now().date().isoformat(),
        "updated": datetime.now().date().isoformat(),
    }
    fm_yaml = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    display_name = emp.get("name", slug)

    return (
        f"---\n{fm_yaml}\n---\n\n"
        f"# {display_name}\n\n"
        "## Profil\n\n"
        "_Stub wygenerowany Phase 1 MVP. Rich profile Phase 3+._\n\n"
        "## Key Patterns\n\n"
        "_Pattern recognition per-pracownik — Phase 3+ (feedback loop Mutation #46)._\n\n"
        "## Content ingestion log\n\n"
        "_Append-only log dziennych emaili przetwarzanych przez system._\n"
    )
