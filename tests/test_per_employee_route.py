"""Unit tests — step2_per_employee_route (Mutation #44 roster check)."""
from __future__ import annotations

import step2_per_employee_route


def _sample_roster() -> dict:
    return {
        "employees": [
            {
                "slug": "jan-kowalski",
                "name": "Jan Kowalski",
                "email": "jan.kowalski@example.com",
                "email_aliases": ["j.kowalski@example.com"],
                "active": True,
            },
            {
                "slug": "anna-nowak",
                "name": "Anna Nowak",
                "email": "anna.nowak@example.com",
                "active": True,
            },
            {
                "slug": "inactive-person",
                "name": "Inactive",
                "email": "inactive@example.com",
                "active": False,
            },
        ]
    }


def test_known_sender_routed_to_slug() -> None:
    emails = [{"id": "m1", "from": "jan.kowalski@example.com", "subject": "test"}]
    routed, unknown = step2_per_employee_route.route(emails, _sample_roster())
    assert "jan-kowalski" in routed
    assert len(routed["jan-kowalski"]) == 1
    assert unknown == []


def test_email_match_case_insensitive() -> None:
    emails = [{"id": "m1", "from": "JAN.KOWALSKI@EXAMPLE.COM"}]
    routed, unknown = step2_per_employee_route.route(emails, _sample_roster())
    assert routed.get("jan-kowalski")
    assert unknown == []


def test_alias_email_matches() -> None:
    emails = [{"id": "m1", "from": "j.kowalski@example.com"}]
    routed, unknown = step2_per_employee_route.route(emails, _sample_roster())
    assert routed.get("jan-kowalski")
    assert unknown == []


def test_unknown_sender_goes_to_unknown_list() -> None:
    emails = [{"id": "m1", "from": "someone.else@random.pl", "subject": "faktura"}]
    routed, unknown = step2_per_employee_route.route(emails, _sample_roster())
    assert routed == {}
    assert len(unknown) == 1
    assert unknown[0]["from"] == "someone.else@random.pl"


def test_inactive_employee_treated_as_unknown() -> None:
    emails = [{"id": "m1", "from": "inactive@example.com"}]
    routed, unknown = step2_per_employee_route.route(emails, _sample_roster())
    assert routed == {}
    assert len(unknown) == 1


def test_multiple_emails_same_employee_grouped() -> None:
    emails = [
        {"id": "m1", "from": "jan.kowalski@example.com"},
        {"id": "m2", "from": "jan.kowalski@example.com"},
        {"id": "m3", "from": "anna.nowak@example.com"},
    ]
    routed, unknown = step2_per_employee_route.route(emails, _sample_roster())
    assert len(routed["jan-kowalski"]) == 2
    assert len(routed["anna-nowak"]) == 1
    assert unknown == []


def test_employee_for_slug_lookup() -> None:
    result = step2_per_employee_route.employee_for_slug("anna-nowak", _sample_roster())
    assert result is not None
    assert result["name"] == "Anna Nowak"


def test_employee_for_slug_missing_returns_none() -> None:
    result = step2_per_employee_route.employee_for_slug("missing", _sample_roster())
    assert result is None


def test_empty_emails_list_empty_output() -> None:
    routed, unknown = step2_per_employee_route.route([], _sample_roster())
    assert routed == {}
    assert unknown == []


def test_empty_roster_all_unknown() -> None:
    emails = [{"id": "m1", "from": "jan.kowalski@example.com"}]
    routed, unknown = step2_per_employee_route.route(emails, {"employees": []})
    assert routed == {}
    assert len(unknown) == 1
