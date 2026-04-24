"""Step 2 — Per-employee routing + Mutation #44 roster check.

Phase 0 stub. Phase 1 implementation:
- Match email.from → employees.yaml entry (strict, NIE fuzzy dla bezpieczeństwa)
- Unknown sender → status='BLOCKED', do NOT write to vault
- Append to vault/pracownicy/{slug}/YYYY-MM-DD.md z frontmatter
- Update _profil.md Content ingestion log (append-only)
- Pattern recognition Phase 3+ (style-pisania.md)

Reuse: MAXIMISEART-SEO/scripts/persona_hyperstition_scanner.py (Mut #44)
"""
from __future__ import annotations


def route(emails: list[dict], employees_config: dict, feedback_state=None) -> dict:
    """Group emails by employee slug. Returns {slug: [emails]} + unknown_senders list."""
    raise NotImplementedError("Phase 1: implement per-employee routing + Mut #44 check")
