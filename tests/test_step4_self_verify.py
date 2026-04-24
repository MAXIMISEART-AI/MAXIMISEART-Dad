"""Unit tests — step4_self_verify STUB mode (deterministic, zero API cost)."""
from __future__ import annotations

from dataclasses import dataclass

import step4_self_verify


@dataclass
class FakeCfg:
    red_team_threshold: float = 0.66
    use_real_api: bool = False


def _sample_routed() -> dict[str, list[dict]]:
    return {
        "jan-kowalski": [
            {"id": "m1", "subject": "Raport", "from": "jan@x.pl"},
            {"id": "m2", "subject": "FTTH Krańcowa", "from": "jan@x.pl"},
        ],
        "anna-nowak": [
            {"id": "m3", "subject": "Spaw", "from": "anna@x.pl"},
        ],
    }


def test_verify_produces_verdicts_for_all_emails() -> None:
    result = step4_self_verify.verify(_sample_routed(), [], FakeCfg())
    assert result["total_count"] == 3
    assert len(result["verdicts"]) == 3
    assert result["stub_mode"] is True


def test_verify_deterministic_same_input_same_output() -> None:
    r1 = step4_self_verify.verify(_sample_routed(), [], FakeCfg())
    r2 = step4_self_verify.verify(_sample_routed(), [], FakeCfg())
    statuses_1 = [v["status"] for v in r1["verdicts"]]
    statuses_2 = [v["status"] for v in r2["verdicts"]]
    assert statuses_1 == statuses_2


def test_verify_unknown_sender_blocked() -> None:
    unknown = [{"id": "u1", "subject": "Faktura", "from": "spam@random.pl"}]
    result = step4_self_verify.verify({}, unknown, FakeCfg())
    assert result["total_count"] == 1
    assert result["verdicts"][0]["status"] == "BLOCKED"
    assert result["verdicts"][0]["layer"] == "persona-hyperstition"


def test_verify_status_distribution() -> None:
    """STUB produces 70% ANSWER / 20% ASK / 10% ABSTAIN — verify mix dla 50 emaili."""
    routed = {"slug": [{"id": f"m{i}", "subject": f"s{i}", "from": "x@y"} for i in range(50)]}
    result = step4_self_verify.verify(routed, [], FakeCfg())
    statuses = [v["status"] for v in result["verdicts"]]
    # Expect mix z przewagą ANSWER
    assert statuses.count("ANSWER") >= 25  # ≥50% ANSWER
    assert "ASK" in statuses or "ABSTAIN" in statuses  # jakieś uncertainty


def test_verify_aggregate_vote_ratio() -> None:
    result = step4_self_verify.verify(_sample_routed(), [], FakeCfg())
    assert 0.0 <= result["vote_ratio"] <= 1.0
    assert result["answered_count"] == sum(1 for v in result["verdicts"] if v["status"] == "ANSWER")


def test_verify_review_required_when_too_many_unknown() -> None:
    """6 unknown senderów → all BLOCKED → vote 0%, REVIEW_REQUIRED."""
    unknown = [{"id": f"u{i}", "subject": "spam", "from": f"x{i}@y"} for i in range(6)]
    result = step4_self_verify.verify({}, unknown, FakeCfg())
    assert result["report_mode"] == "REVIEW_REQUIRED"


def test_verify_top_uncertain_sorted_by_confidence() -> None:
    routed = {"slug": [{"id": f"m{i}", "subject": "t", "from": "x@y"} for i in range(30)]}
    result = step4_self_verify.verify(routed, [], FakeCfg())
    uncertain = result["top_uncertain"]
    assert len(uncertain) <= 5
    if len(uncertain) >= 2:
        # sorted ascending by confidence (lowest first)
        assert uncertain[0]["confidence"] <= uncertain[-1]["confidence"]


def test_use_real_api_raises_not_implemented() -> None:
    import pytest
    with pytest.raises(NotImplementedError):
        step4_self_verify.verify({}, [], FakeCfg(), use_real_api=True)


def test_verify_empty_input_returns_ok() -> None:
    result = step4_self_verify.verify({}, [], FakeCfg())
    assert result["total_count"] == 0
    assert result["vote_ratio"] == 1.0
    assert result["report_mode"] == "OK"
