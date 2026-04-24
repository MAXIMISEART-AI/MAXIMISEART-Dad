"""Step 5 — Obsidian vault update (daily log + _profil.md patterns).

Phase 0 stub. Phase 1+3 implementation:

Writes:
- vault/pracownicy/{slug}/YYYY-MM-DD.md — per-employee daily email log
- vault/pracownicy/{slug}/_profil.md — append to Content ingestion log + patterns
  (per-expert rich profile paradigm, wzór MAXIMISEART-Brain 2026-04-19)
- vault/learning/log.md — chronological entry co zostało dopisane do Excela
  (ZASADA #7 Brain Rule #3)
- vault/synthesis/weekly-*.md — optional weekly roll-up (Phase 5+)

Reuse: ~/.claude/skills/obsidian-cli/ (programmatic vault manipulation)
Reuse: ~/.claude/skills/obsidian-markdown/ (frontmatter + wikilinks)
"""
from __future__ import annotations


def append_daily_log(vault_path, date: str, routed_emails: dict, rows_added: list[dict]) -> None:
    raise NotImplementedError("Phase 1: implement obsidian-cli wrapper")


def update_employee_profile(vault_path, slug: str, correction: dict) -> None:
    """Append to Key Patterns section. Floor Never Drops — never overwrite."""
    raise NotImplementedError("Phase 3: implement per-expert profile append")
