"""MAXIMISEART-Dad daily orchestrator — full 7-step flow.

Phase wiring state (2026-04-24):
  0) step7_feedback_ingest   — Phase 4 WIRED (STUB regex parser)
  1) step1_email_harvest     — Phase 1 WIRED
  2) step2_per_employee_route — Phase 1 WIRED (Mut #44)
  3) step3_excel_extract_update — Phase 2 GATED (tata dostarczy code_mapping.yaml + excel_schema.yaml)
                                 → orchestrator skip'uje gdy cfg.excel_path pusty
  4) step4_self_verify       — Phase 3 WIRED (STUB deterministic, `--use-real-api` gated)
  5) step5_obsidian_update   — Phase 5+ (Phase 1 Obsidian writes są już w Step 2 → obsidian_writer)
  6) step6_report_generate   — Phase 3/6 WIRED (1-pager PL markdown z Red Team verdict)
  7) HALT — czeka na feedback w reports/{date}.md

Rule #6 Portability: wszystkie paths przez env vars.
Rule #7 Graceful Skip: empty mailbox → exit 0.
Rule #1 Floor Never Drops: append-only pisanie do vault.
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
import step3_excel_extract_update  # noqa: E402
import step4_self_verify  # noqa: E402
import step6_report_generate  # noqa: E402
import step7_feedback_ingest  # noqa: E402
from lib.config import DadConfig  # noqa: E402
from lib.gmail_client import OAuthExpiredError  # noqa: E402
from lib.logger import get_logger  # noqa: E402
from lib.obsidian_writer import append_daily_email_log, ensure_employee_folder  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="daily_workflow")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--skip-harvest", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Override Red Team REVIEW_REQUIRED gate.")
    parser.add_argument("--env", type=Path, default=None)
    parser.add_argument("--query", default=None,
                        help="Gmail search query override.")
    parser.add_argument("--skip-feedback", action="store_true",
                        help="Skip Step 0 feedback ingest (dla pierwszego run gdy brak wczorajszego raportu).")
    parser.add_argument("--skip-report", action="store_true",
                        help="Skip Step 6 report (debugging).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = DadConfig.load(env_file=args.env)
    cfg.ensure_runtime_dirs()

    logger = get_logger(cfg.logs_dir, args.date, cfg.log_level)
    logger.info("DAILY_RUN_START | date=%s dry_run=%s test_mode=%s force=%s",
                args.date, args.dry_run, args.test_mode, args.force)

    if cfg.use_real_api:
        alert_path = cfg.state_dir / "ALERT-real-verification-mode.md"
        alert_text = (
            "# Tryb realnej weryfikacji jest jeszcze zablokowany\n\n"
            "Ustaw `DAD_USE_REAL_API=false` i uruchom workflow ponownie. "
            "Aktualnie produkcyjny tryb weryfikacji działa deterministycznie; "
            "realna weryfikacja zostanie włączona dopiero po osobnej akceptacji.\n"
        )
        if not args.dry_run:
            alert_path.write_text(alert_text, encoding="utf-8")
        logger.error("REAL_API_MODE_GATED | alert=%s", alert_path)
        return 4

    # Step 0: Feedback ingest (learning loop — READ wczoraj PRZED pracą)
    feedback_state = _run_step0_feedback(cfg, args, logger)

    # Step 1: Gmail harvest
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
        logger.info("EMPTY_MAILBOX | date=%s — Rule #7 graceful skip", args.date)
        _maybe_generate_empty_report(cfg, args, logger, feedback_state)
        return 0

    logger.info("EMAILS_HARVESTED | count=%d", len(emails))

    # Step 2: Per-employee route (Mut #44)
    routed, unknown = step2_per_employee_route.route(emails, cfg.employees, feedback_state)
    logger.info("EMAILS_ROUTED | employees=%d unknown=%d", len(routed), len(unknown))

    for email in unknown:
        logger.warning("UNKNOWN_SENDER_BLOCKED | from=%s subject=%s id=%s",
                       email.get("from", ""), email.get("subject", ""), email.get("id", ""))

    # Obsidian writes (kombinacja Phase 1 Step 2 + Phase 5 Step 5)
    total_appended = 0
    total_deduped = 0
    if not args.dry_run:
        for slug, employee_emails in routed.items():
            employee = step2_per_employee_route.employee_for_slug(slug, cfg.employees)
            if employee is None:
                logger.error("EMPLOYEE_LOOKUP_FAILED | slug=%s", slug)
                continue
            ensure_employee_folder(cfg.vault_path, slug, employee)
            for email in employee_emails:
                if append_daily_email_log(cfg.vault_path, slug, args.date, employee, email):
                    total_appended += 1
                else:
                    total_deduped += 1

    # Step 3: Excel extract+update - safe buffer sheet only
    rows_added = []
    if cfg.excel_path and str(cfg.excel_path).strip() and cfg.excel_path.exists():
        if args.dry_run:
            logger.info("STEP_3_DRY_RUN | excel_path=%s - no write", cfg.excel_path)
        else:
            try:
                rows_added = step3_excel_extract_update.append_rows(
                    cfg.excel_path,
                    routed,
                    cfg.code_mapping,
                    cfg.excel_schema,
                    snapshots_dir=cfg.state_dir / "excel-snapshots",
                    employees_config=cfg.employees,
                    date=args.date,
                )
                logger.info(
                    "STEP_3_EXCEL | buffer_sheet=%s rows_added=%d",
                    step3_excel_extract_update.BUFFER_SHEET_NAME,
                    len(rows_added),
                )
            except step3_excel_extract_update.ExcelLockedError as e:
                logger.error("STEP_3_EXCEL_LOCKED | %s", e)
                return 5
    else:
        logger.info("STEP_3_SKIPPED | cfg.excel_path pusty/niedostepny")

    # Step 4: Red Team self-verify (Phase 3 STUB mode)
    verdict = step4_self_verify.verify(
        routed, unknown, cfg, use_real_api=cfg.use_real_api,
    )
    logger.info("RED_TEAM_VERDICT | vote=%.0f%% (%d/%d) mode=%s stub=%s",
                verdict["vote_ratio"] * 100, verdict["answered_count"],
                verdict["total_count"], verdict["report_mode"], verdict["stub_mode"])

    if verdict["report_mode"] == "REVIEW_REQUIRED" and not args.force:
        logger.warning("RED_TEAM_BLOCK | mode=REVIEW_REQUIRED — raport wygenerowany z top-5 uncertain")

    # Step 6: Report generate
    if not args.skip_report and not args.dry_run:
        report_path = step6_report_generate.build_report(
            cfg, args.date, routed, unknown, verdict=verdict, feedback_state=feedback_state,
        )
        logger.info("REPORT_GENERATED | path=%s", report_path)

    logger.info(
        "DAILY_RUN_COMPLETE | emails=%d routed=%d unknown=%d appended=%d deduped=%d "
        "vote=%.0f%% mode=%s fatigue=%s",
        len(emails), sum(len(e) for e in routed.values()), len(unknown),
        total_appended, total_deduped,
        verdict["vote_ratio"] * 100, verdict["report_mode"],
        feedback_state.fatigue_level,
    )
    return 0


def _run_step0_feedback(cfg, args, logger):
    """Step 0: feedback ingest. Returns FeedbackState (empty jeśli skip)."""
    if args.skip_feedback:
        logger.info("STEP_0_SKIPPED | --skip-feedback")
        return step7_feedback_ingest.FeedbackState.empty()

    try:
        state = step7_feedback_ingest.load_previous_feedback(cfg, args.date)
        logger.info(
            "STEP_0_FEEDBACK | yesterday_status=%s corrections=%d streak=%d fatigue=%s",
            state.yesterday_status, len(state.corrections),
            state.approval_streak, state.fatigue_level,
        )
        return state
    except Exception:
        logger.warning("STEP_0_FEEDBACK_FAILED\n%s", traceback.format_exc())
        return step7_feedback_ingest.FeedbackState.empty()


def _maybe_generate_empty_report(cfg, args, logger, feedback_state) -> None:
    if args.dry_run or args.skip_report:
        return
    report_path = step6_report_generate.build_report(
        cfg, args.date, routed={}, unknown_senders=[],
        verdict=None, feedback_state=feedback_state,
    )
    logger.info("EMPTY_DAY_REPORT | path=%s", report_path)


if __name__ == "__main__":
    sys.exit(main())
