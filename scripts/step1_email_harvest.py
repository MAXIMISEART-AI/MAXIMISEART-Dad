"""Step 1 — Gmail harvest via native google-api-python-client.

Phase 1 Override D2 (Gmail MCP → native Python) per plan file
C:\\Users\\Arek\\.claude\\plans\\phase-1-mvp-gmail-obsidian.md.

Fallback modes:
- OAuth expired → ALERT-oauth-expired.md w vault + raise
- Empty mailbox → return [], orchestrator handles Rule #7 graceful skip
- Rate limit 429 → exponential backoff w gmail_client
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.gmail_client import OAuthExpiredError, harvest_emails


def harvest(
    cfg,
    date: str,
    test_mode: bool = False,
    query_override: str | None = None,
) -> list[dict[str, Any]]:
    """Harvest emaile dla `date`. Append do JSONL (idempotent via email.id).

    Args:
        cfg: DadConfig
        date: YYYY-MM-DD
        test_mode: True → load fixtures instead of Gmail API
        query_override: Custom Gmail search query (default: newer_than:1d)

    Returns:
        Normalized list emaili.
    """
    if test_mode:
        return _load_test_fixtures()

    lookback = cfg.schedule.get("harvest_lookback_hours", 24)
    query = query_override or f"newer_than:{max(1, lookback // 24)}d"

    try:
        emails = harvest_emails(cfg.oauth_token_path, query=query)
    except OAuthExpiredError as e:
        _write_oauth_alert(cfg, str(e))
        raise

    _append_jsonl_dedup(cfg.state_dir / "raw", date, emails)
    return emails


def _load_test_fixtures() -> list[dict[str, Any]]:
    """Load tests/fixtures/sample_emails/*.json."""
    project_root = Path(__file__).resolve().parents[1]
    fixtures_dir = project_root / "tests" / "fixtures" / "sample_emails"
    emails = []
    for path in sorted(fixtures_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            fixture = json.load(f)
        emails.append({k: v for k, v in fixture.items() if not k.startswith("_")})
    return emails


def _append_jsonl_dedup(raw_dir: Path, date: str, emails: list[dict]) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = raw_dir / f"emails-{date}.jsonl"

    existing_ids: set[str] = set()
    if jsonl_path.exists():
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    existing_ids.add(json.loads(line).get("id", ""))
                except json.JSONDecodeError:
                    continue

    with jsonl_path.open("a", encoding="utf-8") as f:
        for email in emails:
            if email.get("id", "") in existing_ids:
                continue
            f.write(json.dumps(email, ensure_ascii=False) + "\n")


def _write_oauth_alert(cfg, msg: str) -> None:
    alert = cfg.vault_path / "ALERT-oauth-expired.md"
    alert.parent.mkdir(parents=True, exist_ok=True)
    alert.write_text(
        f"# ALERT: Gmail OAuth wygasł\n\n"
        f"**Data:** {cfg.run_time}\n\n"
        f"System nie mógł połączyć z Gmailem.\n\n"
        f"**Szczegóły:** {msg}\n\n"
        f"**Co zrobić:** Uruchom `python scripts/init_wizard.py --phase-1-setup`\n",
        encoding="utf-8",
    )
