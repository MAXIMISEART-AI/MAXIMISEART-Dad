"""MAXIMISEART-Dad daily orchestrator.

Phase 0 stub — structure + CLI only. Step implementations: Phase 1+.

Sekwencja (per CLAUDE.md Rule #1 Floor Never Drops):
  0) step7_feedback_ingest  — READ wczorajszy feedback PRZED pracą (learning)
  1) step1_email_harvest    — Gmail MCP → raw/emails-YYYY-MM-DD.jsonl
  2) step2_per_employee_route — classify + append vault/pracownicy/{slug}/YYYY-MM-DD.md
  3) step3_excel_extract_update — openpyxl append (lock-aware, snapshot)
  4) step4_self_verify       — Red Team vote (Mut #29/#30/#39/#44)
  5) step5_obsidian_update   — daily log + update _profil.md
  6) step6_report_generate   — 1-pager markdown PL
  7) HALT — czeka feedback taty (jutro Step 0 picks up)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

# Bootstrap — add scripts/ to path so siblings can be imported when run as module
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.config import DadConfig  # noqa: E402
from lib.logger import get_logger  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="daily_workflow")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Date to process (YYYY-MM-DD). Default: today.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Excel write + report write (trace only).")
    parser.add_argument("--test-mode", action="store_true",
                        help="Use tests/fixtures/sample_emails/ instead of Gmail.")
    parser.add_argument("--skip-harvest", action="store_true",
                        help="Reuse existing raw/emails-*.jsonl if present.")
    parser.add_argument("--force", action="store_true",
                        help="Override Red Team ABSTAIN gate (DANGEROUS).")
    parser.add_argument("--env", type=Path, default=None,
                        help="Path to .env file (default: project root).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = DadConfig.load(env_file=args.env)
    cfg.ensure_runtime_dirs()

    logger = get_logger(cfg.logs_dir, args.date, cfg.log_level)
    logger.info("DAILY_RUN_START", extra={
        "date": args.date, "dry_run": args.dry_run, "test_mode": args.test_mode,
    })

    # === Phase 0 stub: structure only ===
    logger.warning("PHASE_0_STUB — no step implementations yet. "
                   "Phase 1 adds Step 1+2 (Gmail → Obsidian). "
                   "Phase 2 adds Step 3 (Excel). Phase 3 adds Step 4+6 (Red Team + report). "
                   "Phase 4 adds Step 0+5+7 (learning loop).")

    # Placeholder sequence — każdy step ma własny script w scripts/step*.py
    # Full orchestration wire-up w Phase 1.
    logger.info("DAILY_RUN_COMPLETE", extra={"status": "stub", "steps_executed": 0})
    return 0


if __name__ == "__main__":
    sys.exit(main())
