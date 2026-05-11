"""Step 5 — Phase 5+ Obsidian extension placeholder.

Current production wiring:
- Phase 1 daily email logs are written from daily_workflow.py via lib.obsidian_writer.
- Phase 4 profile/known-error learning updates are handled by step7_feedback_ingest.py.

Future Phase 5+ extension may centralize:

Writes:
- vault/learning/log.md — chronological entry co zostało dopisane do Excela
- vault/synthesis/weekly-*.md — optional weekly roll-up (Phase 5+)
"""
from __future__ import annotations


def append_daily_log(vault_path, date: str, routed_emails: dict, rows_added: list[dict]) -> None:
    raise NotImplementedError("Phase 5+: optional centralized Obsidian learning log")


def update_employee_profile(vault_path, slug: str, correction: dict) -> None:
    """Append to Key Patterns section. Floor Never Drops — never overwrite."""
    raise NotImplementedError("Phase 5+: optional profile update shim; current flow uses step7_feedback_ingest")
