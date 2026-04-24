"""Unit tests — step6_report_generate (1-pager PL markdown)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import step6_report_generate


@dataclass
class FakeCfg:
    reports_dir: Path = Path(".")
    employees: dict = field(default_factory=lambda: {
        "employees": [
            {"slug": "jan-kowalski", "name": "Jan Kowalski"},
            {"slug": "anna-nowak", "name": "Anna Nowak"},
        ]
    })


@dataclass
class FakeFeedback:
    fatigue_level: str = "GREEN"
    approval_streak: int = 0
    corrections: list = field(default_factory=list)


def _sample_routed() -> dict:
    return {
        "jan-kowalski": [
            {"id": "m1", "subject": "Raport 2026-04-24", "from": "jan@x.pl"},
            {"id": "m2", "subject": "FTTH Krańcowa 12", "from": "jan@x.pl"},
        ],
        "anna-nowak": [{"id": "m3", "subject": "Spaw", "from": "anna@x.pl"}],
    }


def _sample_verdict(mode: str = "OK") -> dict:
    return {
        "total_count": 3,
        "answered_count": 2 if mode == "OK" else 0,
        "vote_ratio": 0.67 if mode == "OK" else 0.20,
        "threshold": 0.66,
        "verdicts": [],
        "top_uncertain": [] if mode == "OK" else [
            {"row_index": 1, "employee_name": "Jan Kowalski", "rationale": "Ambiguous"}
        ],
        "report_mode": mode,
        "stub_mode": True,
    }


def test_build_report_creates_file(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", _sample_routed(), [],
        verdict=_sample_verdict(), feedback_state=FakeFeedback(),
    )
    assert path.exists()
    assert path.name == "2026-04-24.md"


def test_report_contains_expected_sections(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", _sample_routed(), [],
        verdict=_sample_verdict(), feedback_state=FakeFeedback(),
    )
    content = path.read_text(encoding="utf-8")
    assert "# Raport dzienny" in content
    assert "## Podsumowanie" in content
    assert "## Per pracownik" in content
    assert "## Feedback taty" in content
    assert "## Statystyki" in content


def test_report_frontmatter_contains_date_and_status(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", _sample_routed(), [],
        verdict=_sample_verdict(), feedback_state=FakeFeedback(),
    )
    content = path.read_text(encoding="utf-8")
    assert "date: '2026-04-24'" in content or "date: 2026-04-24" in content
    assert "status: AWAITING_FEEDBACK" in content
    assert "fatigue_level: GREEN" in content


def test_report_unknown_senders_flagged(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    unknown = [{"id": "u1", "from": "spam@x.pl", "subject": "Faktura"}]
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", {}, unknown,
        verdict=_sample_verdict(mode="REVIEW_REQUIRED"),
        feedback_state=FakeFeedback(),
    )
    content = path.read_text(encoding="utf-8")
    assert "## Wymagają uwagi" in content
    assert "Nieznani nadawcy" in content
    assert "spam@x.pl" in content


def test_report_review_required_status(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", _sample_routed(), [],
        verdict=_sample_verdict(mode="REVIEW_REQUIRED"),
        feedback_state=FakeFeedback(),
    )
    content = path.read_text(encoding="utf-8")
    assert "status: REVIEW_REQUIRED" in content


def test_report_fatigue_critical_inject_banner(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    feedback = FakeFeedback(fatigue_level="CRITICAL", approval_streak=3)
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", _sample_routed(), [],
        verdict=_sample_verdict(), feedback_state=feedback,
    )
    content = path.read_text(encoding="utf-8")
    assert "PILNE" in content
    assert "3 dni bez" in content


def test_report_empty_mailbox(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", {}, [], verdict=None, feedback_state=FakeFeedback(),
    )
    content = path.read_text(encoding="utf-8")
    assert "0 emaili" in content
    assert "skrzynka była pusta" in content


def test_report_weekday_in_polish(tmp_path: Path) -> None:
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    # 2026-04-24 is Friday (piątek)
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", _sample_routed(), [],
        verdict=_sample_verdict(), feedback_state=FakeFeedback(),
    )
    content = path.read_text(encoding="utf-8")
    assert "piątek" in content


def test_report_no_ai_claude_anthropic_mention(tmp_path: Path) -> None:
    """D16 identity rule — zero mention w tata-facing output."""
    cfg = FakeCfg(reports_dir=tmp_path / "reports")
    path = step6_report_generate.build_report(
        cfg, "2026-04-24", _sample_routed(), [],
        verdict=_sample_verdict(), feedback_state=FakeFeedback(),
    )
    content = path.read_text(encoding="utf-8").lower()
    assert "claude" not in content
    assert "anthropic" not in content
    assert " ai " not in content
    assert "llm" not in content
