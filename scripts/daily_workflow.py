"""MAXIMISEART-Dad daily orchestrator — Phase 1 MVP wire-up.

Phase 1 scope: Step 1 (Gmail harvest) + Step 2 (per-employee route) + Obsidian write.
NIE: Excel (Phase 2), Red Team (Phase 3), Learning loop (Phase 4).

Sekwencja Phase 1:
  1) step1_email_harvest  — Gmail native client → runtime/state/raw/emails-YYYY-MM-DD.jsonl
  2) step2_per_employee_route — roster check (Mut #44) + group per pracownik
  3) obsidian_writer      — pure Python markdown append do vault/pracownicy/{slug}/YYYY-MM-DD.md

Phase 2+ steps (step3-7) pozostają jako stuby z NotImplementedError — niewywoływane.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import step1_email_harvest  # noqa: E402
import step2_per_employee_route  # noqa: E402
from lib.config import DadConfig  # noqa: E402
from lib.gmail_client import OAuthExpiredError  # noqa: E402
from lib.logger import get_logger  # noqa: E402
from lib.obsidian_writer import append_daily_email_log, ensure_employee_folder  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="daily_workflow")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Date to process (YYYY-MM-DD). Default: today.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip vault + Excel write (trace only).")
    parser.add_argument("--test-mode", action="store_true",
                        help="Use tests/fixtures/sample_emails/ instead of Gmail.")
    parser.add_argument("--skip-harvest", action="store_true",
                        help="Reuse existing raw/emails-*.jsonl if present (not Phase 1).")
    parser.add_argument("--force", action="store_true",
                        help="Override Red Team gate (Phase 3+, ignored Phase 1).")
    parser.add_argument("--env", type=Path, default=None,
                        help="Path to .env file (default: project root).")
    parser.add_argument("--query", default=None,
                        help="Gmail search query override (Phase 1 test: '[DAD-TEST] newer_than:1d').")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = DadConfig.load(env_file=args.env)
    cfg.ensure_runtime_dirs()

    logger = get_logger(cfg.logs_dir, args.date, cfg.log_level)
    logger.info("DAILY_RUN_START | date=%s dry_run=%s test_mode=%s",
                args.date, args.dry_run, args.test_mode)

    try:
        emails = step1_email_harvest.harvest(
            cfg, args.date, test_mode=args.test_mode, query_override=args.query
        )
    except OAuthExpiredError as e:
        logger.error("OAUTH_EXPIRED | %s", e)
        return 2
    except Exception:
        logger.error("HARVEST_FAILED\n%s", traceback.format_exc())
        return 3

    if not emails:
        logger.info("EMPTY_MAILBOX | date=%s — graceful skip per Rule #7", args.date)
        return 0

    logger.info("EMAILS_HARVESTED | count=%d", len(emails))

    routed, unknown = step2_per_employee_route.route(emails, cfg.employees)

    logger.info("EMAILS_ROUTED | employees=%d unknown_senders=%d",
                len(routed), len(unknown))

    for email in unknown:
        logger.warning("UNKNOWN_SENDER_BLOCKED | from=%s subject=%s id=%s",
                       email.get("from", ""), email.get("subject", ""), email.get("id", ""))

    if args.dry_run:
        logger.info("DRY_RUN | skipping vault writes")
        _log_dry_run_summary(logger, routed, unknown)
        return 0

    total_appended = 0
    total_deduped = 0
    for slug, employee_emails in routed.items():
        employee = step2_per_employee_route.employee_for_slug(slug, cfg.employees)
        if employee is None:
            logger.error("EMPLOYEE_LOOKUP_FAILED | slug=%s", slug)
            continue
        ensure_employee_folder(cfg.vault_path, slug, employee)
        for email in employee_emails:
            appended = append_daily_email_log(
                cfg.vault_path, slug, args.date, employee, email
            )
            if appended:
                total_appended += 1
            else:
                total_deduped += 1

    logger.info("PHASE_1_COMPLETE | appended=%d deduped=%d unknown=%d",
                total_appended, total_deduped, len(unknown))
    return 0


def _log_dry_run_summary(logger, routed: dict, unknown: list) -> None:
    for slug, emails in routed.items():
        logger.info("DRY_RUN_ROUTED | slug=%s count=%d subjects=%s",
                    slug, len(emails), [e.get("subject", "") for e in emails])
    for email in unknown:
        logger.info("DRY_RUN_BLOCKED | from=%s subject=%s",
                    email.get("from", ""), email.get("subject", ""))


if __name__ == "__main__":
    sys.exit(main())
