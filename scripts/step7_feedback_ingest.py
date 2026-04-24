"""Step 7 — Feedback ingest (Rule #5 Auto-Learn Post-Delivery).

Runs NA POCZĄTKU każdego daily run (PRZED Step 1). Czyta wczorajszy raport,
parsuje `## Feedback taty`, updates learning files. Agent consume context
nast day w Step 2/3/4.

STUB mode (default): regex/keyword parsing (no API calls).
Real API mode: Haiku parser (post-first-klient gated).

Reuse: MAXIMISEART-SEO/scripts/approval_log.py (Mut #46 Layer 1)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass
class FeedbackState:
    corrections: list[dict] = field(default_factory=list)
    approval_streak: int = 0
    fatigue_level: str = "GREEN"
    yesterday_status: str = "UNKNOWN"

    @classmethod
    def empty(cls) -> "FeedbackState":
        return cls()


def load_previous_feedback(cfg, today: str) -> FeedbackState:
    """Runs jako Step 0 każdego daily run. Returns FeedbackState dla Step 2/3/4 context.

    Args:
        cfg: DadConfig
        today: YYYY-MM-DD

    Returns:
        FeedbackState z corrections + approval_streak + fatigue_level
    """
    yesterday = (datetime.fromisoformat(today).date() - timedelta(days=1)).isoformat()
    yesterday_report = cfg.reports_dir / f"{yesterday}.md"

    if not yesterday_report.exists():
        return FeedbackState.empty()

    content = yesterday_report.read_text(encoding="utf-8")
    feedback_block = _extract_section(content, "## Feedback taty")
    feedback_clean = _strip_html_comments(feedback_block).strip()

    state = FeedbackState()

    if not feedback_clean or feedback_clean.lower() in ("ok", "ok.", ""):
        _log_approval(cfg, today, yesterday, decision="APPROVE" if feedback_clean else "NO_FEEDBACK",
                      raw_text=feedback_clean)
        state.approval_streak = _compute_streak(cfg.state_dir / "approval-log.jsonl", no_feedback_only=True)
        state.fatigue_level = _compute_fatigue(state.approval_streak, cfg.fatigue_critical_days)
        state.yesterday_status = "APPROVED" if feedback_clean else "NO_FEEDBACK"
        return state

    parsed = _stub_parse_feedback(feedback_clean)
    state.corrections = parsed
    state.yesterday_status = "CORRECTED"

    _log_approval(cfg, today, yesterday, decision="CORRECT", raw_text=feedback_clean, parsed=parsed)
    _append_feedback_log(cfg.learning_dir / "feedback-log.jsonl", yesterday, feedback_clean, parsed)

    for correction in parsed:
        if correction.get("confidence", 0.0) >= 0.7:
            _update_known_errors(cfg.vault_path / "learning" / "known-errors.md", correction, yesterday)
            if correction.get("employee_slug"):
                _update_employee_patterns(
                    cfg.vault_path / "pracownicy" / correction["employee_slug"] / "_profil.md",
                    correction,
                    yesterday,
                )

    state.approval_streak = 0
    state.fatigue_level = "GREEN"
    return state


def _extract_section(markdown: str, heading: str) -> str:
    """Line-based section extractor. Returns content between `heading` i next `## ` line."""
    lines = markdown.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start, len(lines)):
        line_stripped = lines[i].strip()
        if line_stripped.startswith("## ") and line_stripped != heading:
            end = i
            break
    return "\n".join(lines[start:end])


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _stub_parse_feedback(text: str) -> list[dict]:
    """Simple regex-based parser. Real API mode (Haiku) Phase 4.1+."""
    corrections = []
    lines = [ln.strip("- ").strip() for ln in text.split("\n") if ln.strip()]

    for line in lines:
        if not line or line.lower() in ("ok", "ok."):
            continue

        slug = _guess_employee_slug(line)
        correction = {
            "raw": line,
            "employee_slug": slug,
            "correction_type": _classify_correction(line),
            "confidence": 0.75 if slug else 0.55,
            "parsed_by": "stub-regex",
        }
        corrections.append(correction)

    return corrections


def _guess_employee_slug(line: str) -> str | None:
    name_match = re.search(r"\b([A-ZŻŹĆŃÓŁŚĄĘ][a-zżźćńółśąę]+)\b", line)
    if name_match:
        return name_match.group(1).lower()
    return None


def _classify_correction(line: str) -> str:
    low = line.lower()
    if "kod" in low:
        return "wrong_code"
    if "ilość" in low or "liczb" in low or "sztuk" in low:
        return "wrong_quantity"
    if "lokacj" in low or "ulic" in low or "adres" in low or "blok" in low:
        return "wrong_location"
    return "other"


def _log_approval(
    cfg, today: str, yesterday: str, decision: str,
    raw_text: str = "", parsed: list | None = None,
) -> None:
    log_path = cfg.state_dir / "approval-log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(ZoneInfo("Europe/Warsaw")).isoformat(),
        "report_date": yesterday,
        "evaluated_at_run": today,
        "decision": decision,
        "item_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16],
        "corrections_count": len(parsed) if parsed else 0,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_feedback_log(
    log_path: Path, report_date: str, raw_text: str, parsed: list[dict],
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(ZoneInfo("Europe/Warsaw")).isoformat(),
        "report_date": report_date,
        "raw": raw_text,
        "parsed": parsed,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _compute_streak(log_path: Path, no_feedback_only: bool) -> int:
    if not log_path.exists():
        return 0
    streak = 0
    with log_path.open("r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        decision = entry.get("decision", "")
        if no_feedback_only and decision == "NO_FEEDBACK":
            streak += 1
        elif not no_feedback_only:
            streak += 1
        else:
            break
    return streak


def _compute_fatigue(streak: int, critical_days: int) -> str:
    if streak >= critical_days:
        return "CRITICAL"
    if streak >= critical_days - 1:
        return "RED"
    if streak >= 1:
        return "YELLOW"
    return "GREEN"


def _update_known_errors(errors_path: Path, correction: dict, date: str) -> None:
    errors_path.parent.mkdir(parents=True, exist_ok=True)
    entry_line = (
        f"- [{date}] **{correction.get('correction_type', 'other')}** "
        f"pracownik=`{correction.get('employee_slug', '?')}` "
        f"— {correction.get('raw', '')}"
    )

    if not errors_path.exists():
        errors_path.write_text(
            "# Znane błędy — nie powtarzaj\n\n"
            "_Append-only log. Każdy wpis to correction z feedbacku taty._\n\n",
            encoding="utf-8",
        )

    with errors_path.open("a", encoding="utf-8") as f:
        f.write(entry_line + "\n")


def _update_employee_patterns(profil_path: Path, correction: dict, date: str) -> None:
    if not profil_path.exists():
        return

    content = profil_path.read_text(encoding="utf-8")
    marker = "## Key Patterns"
    pattern_entry = (
        f"- [{date}] ({correction.get('correction_type', 'other')}) "
        f"{correction.get('raw', '')}"
    )

    if marker in content:
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.strip() == marker:
                insert_at = i + 1
                while insert_at < len(lines) and (
                    lines[insert_at].strip().startswith("_") or lines[insert_at].strip() == ""
                ):
                    insert_at += 1
                lines.insert(insert_at, pattern_entry)
                break
        profil_path.write_text("\n".join(lines), encoding="utf-8")
    else:
        with profil_path.open("a", encoding="utf-8") as f:
            f.write(f"\n## Key Patterns\n\n{pattern_entry}\n")
