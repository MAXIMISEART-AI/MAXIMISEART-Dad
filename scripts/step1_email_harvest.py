"""Step 1 — Gmail MCP harvest → runtime/state/raw/emails-YYYY-MM-DD.jsonl.

Phase 0 stub. Phase 1 implementation:
- Use google-auth-oauthlib dla token cache (init wizard creates token)
- Gmail API: list(query='newer_than:1d') → get(msg_id) full payload
- Write JSONL: {id, from, to, subject, body_text, received_at, attachments_count}
- Fallback modes:
  - OAuth expired → write state/ALERT-oauth-expired.md + exit 2
  - Rate limit → exponential backoff + cache state/gmail-cache-YYYY-MM-DD.json
  - Empty mailbox → return [], caller handles graceful skip
"""
from __future__ import annotations

from pathlib import Path


def harvest(cfg, date: str, feedback_state=None) -> list[dict]:
    """Return list of normalized email dicts.

    Phase 0 stub returns empty list.
    """
    raise NotImplementedError("Phase 1: implement Gmail MCP harvest")


def load_test_fixtures(fixtures_dir: Path) -> list[dict]:
    """Test mode — load JSON fixtures from tests/fixtures/sample_emails/."""
    import json
    emails = []
    for path in sorted(fixtures_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            emails.append(json.load(f))
    return emails
