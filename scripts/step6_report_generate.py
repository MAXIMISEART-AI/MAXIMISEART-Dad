"""Step 6 — Generate 1-pager markdown raport PL dla taty.

Output: vault/reports/YYYY-MM-DD.md

Constraints (CLAUDE.md):
- ZERO mention "Claude", "Anthropic", "AI", "LLM" w tata-facing
- Polski formalny ton
- Status: AWAITING_FEEDBACK (Rule #3 Human in the Loop)
- Inject fatigue warning gdy CRITICAL (Mut #46)
- Inject REVIEW_REQUIRED banner gdy Red Team vote < threshold
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

WEEKDAY_PL = {
    0: "poniedziałek", 1: "wtorek", 2: "środa", 3: "czwartek",
    4: "piątek", 5: "sobota", 6: "niedziela",
}


def build_report(
    cfg,
    date: str,
    routed: dict[str, list[dict]],
    unknown_senders: list[dict],
    verdict: dict | None = None,
    feedback_state: Any | None = None,
) -> Path:
    """Render 1-pager markdown do vault/reports/{date}.md.

    Args:
        cfg: DadConfig
        date: YYYY-MM-DD
        routed: {slug: [emails]} output Step 2
        unknown_senders: emails BLOCKED Mut #44
        verdict: Optional Red Team verdict z Step 4 (None = Phase 1, no verdict)
        feedback_state: Optional from Step 7 (fatigue level, corrections history)

    Returns:
        Path do wygenerowanego raportu.
    """
    report_path = cfg.reports_dir / f"{date}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    total_emails = sum(len(e) for e in routed.values()) + len(unknown_senders)
    total_employees = len(routed)

    frontmatter = _build_frontmatter(
        date, total_emails, total_employees, verdict, unknown_senders, feedback_state
    )

    sections = []
    if feedback_state and getattr(feedback_state, "fatigue_level", "GREEN") == "CRITICAL":
        sections.append(_render_fatigue_banner(feedback_state))

    sections.append(_render_header(date))
    sections.append(_render_summary(total_emails, total_employees, routed, verdict))

    if total_employees > 0:
        sections.append(_render_per_employee(routed, cfg.employees))

    if unknown_senders or (verdict and _has_review_items(verdict)):
        sections.append(_render_review_section(unknown_senders, verdict))

    sections.append(_render_feedback_field())
    sections.append(_render_statistics(feedback_state))

    body = "\n\n".join(sections)
    content = f"---\n{frontmatter}\n---\n\n{body}\n"
    report_path.write_text(content, encoding="utf-8")
    return report_path


def _build_frontmatter(
    date: str,
    emails_count: int,
    employees_active: int,
    verdict: dict | None,
    unknown: list[dict],
    feedback_state: Any | None,
) -> str:
    fm = {
        "date": date,
        "emails_processed": emails_count,
        "employees_active": employees_active,
        "blocked_senders": len(unknown),
        "red_team_vote": _format_vote(verdict),
        "fatigue_level": getattr(feedback_state, "fatigue_level", "GREEN") if feedback_state else "GREEN",
        "status": _determine_status(verdict),
        "generated": datetime.now().isoformat(timespec="seconds"),
    }
    return yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()


def _format_vote(verdict: dict | None) -> str:
    if verdict is None:
        return "—"
    ratio = verdict.get("vote_ratio", 0.0)
    answered = verdict.get("answered_count", 0)
    total = verdict.get("total_count", 0)
    return f"{answered}/{total} ({ratio:.0%})"


def _determine_status(verdict: dict | None) -> str:
    if verdict is None:
        return "AWAITING_FEEDBACK"
    if verdict.get("report_mode") == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    return "AWAITING_FEEDBACK"


def _render_fatigue_banner(feedback_state: Any) -> str:
    streak = getattr(feedback_state, "approval_streak", 0)
    return (
        "> ⚠️ **PILNE:** System wykrył " + str(streak) + " dni bez Twojego feedbacku.\n"
        "> Przeglądnij ostatnie raporty w folderze `reports/`.\n"
        "> Aktualizacja wzorców wstrzymana do czasu Twojej reakcji."
    )


def _render_header(date: str) -> str:
    dt = datetime.strptime(date, "%Y-%m-%d")
    weekday = WEEKDAY_PL[dt.weekday()]
    return f"# Raport dzienny — {date} ({weekday})"


def _render_summary(
    total_emails: int,
    total_employees: int,
    routed: dict,
    verdict: dict | None,
) -> str:
    lines = ["## Podsumowanie", ""]
    if total_emails == 0:
        lines.append("- 0 emaili dzisiaj")
        lines.append("- System działa poprawnie, skrzynka była pusta")
        return "\n".join(lines)

    lines.append(f"- {total_emails} emaili przetworzonych")

    if verdict is not None:
        rows = verdict.get("total_count", 0)
        lines.append(f"- {rows} wierszy dopisanych do Excela")
    else:
        lines.append(f"- {sum(len(e) for e in routed.values())} emaili zapisanych per pracownik")

    lines.append(f"- {total_employees} pracowników aktywnych dzisiaj")
    return "\n".join(lines)


def _render_per_employee(routed: dict[str, list[dict]], employees_config: dict) -> str:
    lines = ["## Per pracownik", "", "| Pracownik | Emaile | Tematy |", "|-----------|--------|--------|"]
    employees_map = {e.get("slug"): e for e in employees_config.get("employees", [])}
    for slug, emails in sorted(routed.items()):
        emp = employees_map.get(slug, {})
        name = emp.get("name", slug)
        subjects = ", ".join(
            f"\"{e.get('subject', '')[:40]}\"" for e in emails[:3]
        )
        if len(emails) > 3:
            subjects += f" (+{len(emails) - 3} więcej)"
        lines.append(f"| {name} | {len(emails)} | {subjects} |")
    return "\n".join(lines)


def _render_review_section(unknown: list[dict], verdict: dict | None) -> str:
    lines = ["## Wymagają uwagi", ""]

    if unknown:
        lines.append("### Nieznani nadawcy (zablokowane)")
        lines.append("")
        for email in unknown[:5]:
            sender = email.get("from", "(brak)")
            subject = email.get("subject", "(brak tematu)")
            lines.append(f"- **Od:** `{sender}` — _{subject}_")
        if len(unknown) > 5:
            lines.append(f"- _...oraz {len(unknown) - 5} innych (sprawdź logi)_")
        lines.append("")
        lines.append(
            "_Jeśli któryś z powyższych to rzeczywiście pracownik — dodaj go do "
            "listy pracowników i uruchom ponownie._"
        )
        lines.append("")

    if verdict:
        uncertain = verdict.get("top_uncertain", [])
        if uncertain:
            lines.append("### Wiersze do weryfikacji")
            lines.append("")
            for row in uncertain[:5]:
                lines.append(f"- **Wiersz #{row.get('row_index', '?')}** — "
                             f"{row.get('employee_name', '?')}: "
                             f"{row.get('rationale', '')}")
            lines.append("")

    return "\n".join(lines)


def _render_feedback_field() -> str:
    return (
        "## Feedback taty\n"
        "\n"
        "<!-- Wpisz 'OK' jeśli wszystko się zgadza, albo opisz co poprawić. -->\n"
        "<!-- Np: 'Jan miał kod 2 nie 1' lub 'Anna była na Krańcowej 12 nie 22'. -->\n"
        "\n"
        "\n"
    )


def _render_statistics(feedback_state: Any | None) -> str:
    lines = ["## Statystyki"]
    if feedback_state:
        streak = getattr(feedback_state, "approval_streak", 0)
        fatigue = getattr(feedback_state, "fatigue_level", "GREEN")
        lines.append(f"- Seria zatwierdzeń: {streak} dni z rzędu")
        lines.append(f"- Poziom uwagi: {fatigue}")
    else:
        lines.append("- _Statystyki będą dostępne po pierwszym zatwierdzeniu raportu._")
    return "\n".join(lines)


def _has_review_items(verdict: dict) -> bool:
    return (verdict.get("report_mode") == "REVIEW_REQUIRED"
            or len(verdict.get("top_uncertain", [])) > 0)
