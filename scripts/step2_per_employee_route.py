"""Step 2 — Per-employee routing + Mutation #44 Persona Hyperstition roster check.

Classify emaile per pracownik. Unknown sender (spoza employees.yaml) = BLOCKED
(Mut #44 Persona Hyperstition — nigdy nie halucynuj pracownika).

Per D11 Phase 1: kody prac NIE są classifikowane (Phase 2 z code_mapping.yaml).
"""
from __future__ import annotations

from typing import Any


class RosterIndex:
    """Case-insensitive index employees.yaml dla matching."""

    def __init__(self, employees_config: dict):
        self._by_email: dict[str, dict] = {}
        self._active: list[dict] = []
        for emp in employees_config.get("employees", []):
            if not emp.get("active", False):
                continue
            self._active.append(emp)
            email = emp.get("email", "").lower().strip()
            if email:
                self._by_email[email] = emp
            for alias in emp.get("email_aliases", []) or []:
                alias_email = alias.lower().strip()
                if alias_email:
                    self._by_email[alias_email] = emp

    def match(self, from_email: str) -> dict | None:
        return self._by_email.get(from_email.lower().strip())

    @property
    def active_count(self) -> int:
        return len(self._active)


def route(
    emails: list[dict[str, Any]],
    employees_config: dict,
    feedback_state: Any | None = None,  # noqa: ARG001 — Phase 4+ injection slot
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Group emaile by employee slug. Unknown senders = BLOCKED (Mut #44).

    Args:
        emails: Normalized emaile z Step 1
        employees_config: Loaded config/employees.yaml
        feedback_state: Opcjonalny context z Step 7 — unused Phase 1, consumed Phase 4+

    Returns:
        (routed: {slug: [emails]}, unknown_senders: [emails])
    """
    del feedback_state  # Phase 4+ will inject learned patterns into matching
    roster = RosterIndex(employees_config)
    routed: dict[str, list[dict]] = {}
    unknown: list[dict] = []

    for email in emails:
        from_email = email.get("from", "")
        match = roster.match(from_email)
        if match is None:
            unknown.append(email)
            continue
        slug = match.get("slug", "")
        routed.setdefault(slug, []).append(email)

    return routed, unknown


def employee_for_slug(slug: str, employees_config: dict) -> dict | None:
    """Lookup employee dict by slug (dla Obsidian writer frontmatter)."""
    for emp in employees_config.get("employees", []):
        if emp.get("slug") == slug:
            return emp
    return None
