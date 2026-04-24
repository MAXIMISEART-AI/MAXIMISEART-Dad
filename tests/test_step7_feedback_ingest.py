"""Unit tests — step7_feedback_ingest (Rule #5 Auto-Learn)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import step7_feedback_ingest


@dataclass
class FakeCfg:
    reports_dir: Path
    state_dir: Path
    learning_dir: Path
    vault_path: Path
    fatigue_critical_days: int = 3


def _cfg(tmp_path: Path) -> FakeCfg:
    return FakeCfg(
        reports_dir=tmp_path / "reports",
        state_dir=tmp_path / "state",
        learning_dir=tmp_path / "learning",
        vault_path=tmp_path / "vault",
    )


def _write_report(cfg: FakeCfg, date: str, feedback_text: str) -> None:
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "---\ndate: '" + date + "'\n---\n\n"
        "# Raport\n\n## Podsumowanie\n\nBla bla.\n\n"
        f"## Feedback taty\n\n{feedback_text}\n\n"
        "## Statystyki\n"
    )
    (cfg.reports_dir / f"{date}.md").write_text(content, encoding="utf-8")


def test_empty_feedback_no_previous_report_returns_empty(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    result = step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-24")
    assert result.approval_streak == 0
    assert result.fatigue_level == "GREEN"
    assert result.corrections == []


def test_ok_feedback_logged_as_approval(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write_report(cfg, "2026-04-23", "OK")
    result = step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-24")
    assert result.corrections == []
    assert result.yesterday_status == "APPROVED"

    log = cfg.state_dir / "approval-log.jsonl"
    assert log.exists()
    assert "APPROVE" in log.read_text(encoding="utf-8")


def test_no_feedback_increments_streak(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write_report(cfg, "2026-04-23", "")
    result = step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-24")
    assert result.yesterday_status == "NO_FEEDBACK"
    assert result.approval_streak >= 1


def test_critical_fatigue_when_streak_reaches_threshold(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write_report(cfg, "2026-04-20", "")
    _write_report(cfg, "2026-04-21", "")
    _write_report(cfg, "2026-04-22", "")
    _write_report(cfg, "2026-04-23", "")

    step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-21")
    step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-22")
    step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-23")
    result = step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-24")

    assert result.approval_streak >= 3
    assert result.fatigue_level == "CRITICAL"


def test_corrections_parsed_and_propagated(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    # Pre-create employee profile
    profil_dir = cfg.vault_path / "pracownicy" / "jan"
    profil_dir.mkdir(parents=True)
    (profil_dir / "_profil.md").write_text(
        "---\ntags: [pracownik]\n---\n\n# Jan\n\n## Key Patterns\n\n_Stub._\n",
        encoding="utf-8",
    )

    _write_report(cfg, "2026-04-23", "Jan miał kod 2 nie 1")
    result = step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-24")

    assert len(result.corrections) == 1
    assert result.yesterday_status == "CORRECTED"
    assert result.corrections[0]["correction_type"] == "wrong_code"

    feedback_log = cfg.learning_dir / "feedback-log.jsonl"
    assert feedback_log.exists()
    assert "kod 2 nie 1" in feedback_log.read_text(encoding="utf-8")

    known_errors = cfg.vault_path / "learning" / "known-errors.md"
    assert known_errors.exists()
    assert "wrong_code" in known_errors.read_text(encoding="utf-8")


def test_feedback_with_html_comments_stripped(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    feedback_with_comments = (
        "<!-- Wpisz OK lub opisz co poprawić -->\n"
        "Jan miał kod 2"
    )
    _write_report(cfg, "2026-04-23", feedback_with_comments)
    result = step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-24")
    assert result.yesterday_status == "CORRECTED"
    assert len(result.corrections) == 1


def test_only_comments_treated_as_empty(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write_report(cfg, "2026-04-23", "<!-- Wpisz OK -->\n<!-- drugi -->")
    result = step7_feedback_ingest.load_previous_feedback(cfg, "2026-04-24")
    assert result.corrections == []
    assert result.yesterday_status == "NO_FEEDBACK"
