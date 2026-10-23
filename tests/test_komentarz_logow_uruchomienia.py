"""Komentarz Logów Uruchomienia w Skrzynce Zgłoszeń (#320): podsumowanie z rekordu Logów i podział długiego JSON.

Logi ponad limit komentarza GitHuba wymagałyby przez HTTP setek Komunikatów, więc podział sprawdza wysyłka
zbudowana wprost z rekordu (``logi_post``): jej części to dokładnie komentarze, które kolejka dopisuje do issue.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from rozliczenia.centrum.report_box import COMMENT_LIMIT
from rozliczenia.centrum.run_logs import RunLog, logi_post, summary_markdown

RUN_ID = "627b45fe219e4274b722953c34d4af54"
STOP = {"kind": "stop", "code": "ZLA_KONFIGURACJA_WYKONAWCOW", "what": "Co.", "where": "Gdzie.", "action": "Zrób."}
JSON_PART = re.compile(r"\n````json\n(.*)\n````\n\n</details>\n\Z", re.DOTALL)


def warning(code: str, what: str = "Co.") -> dict[str, str]:
    return {"kind": "warning", "code": code, "what": what, "where": "Gdzie.", "action": "Zrób."}


def record(**changes: Any) -> RunLog:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "process": "settlement",
        "mode": "zapis",
        "period": "08_14_09_2026",
        "started_at": "2026-10-23T20:47:20.846240Z",
        "ended_at": "2026-10-23T20:47:20.857060Z",
        "duration_ms": 10,
        "tool": {"wydanie": None, "commit": "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"},
        "result": "OK",
        "ending": "finished",
        "stop_kind": None,
        "issue_count": 0,
        "messages": [],
        "notices": [],
        "summary": None,
        "phases": [],
        "templates": [],
        "environment": {"system": "Windows-11", "python": "3.12.10", "files": None},
        "trace": None,
        "diagnosis": None,
    }
    return RunLog.model_validate({**fields, **changes})


def test_podsumowanie_ma_proces_tryb_okres_wynik_czas_komunikaty_wydanie_i_uruchomienie() -> None:
    assert summary_markdown(record()) == (
        "**Logi Uruchomienia**: Przebieg rozliczeń, zapis, okres 08_14_09_2026\n"
        "\n"
        "- Wynik: OK\n"
        "- Czas: 10 ms\n"
        "- Komunikaty: brak\n"
        "- Wydanie: brak, commit 3c1d0a9\n"
        f"- Uruchomienie: {RUN_ID}, start 2026-10-23 20:47:20 UTC"
    )


SUMMARY_LINES: dict[str, tuple[dict[str, Any], list[str]]] = {
    "przygotowanie-podglad": (
        {"process": "preparation", "mode": "podgląd"},
        ["**Logi Uruchomienia**: Przygotowanie pliku zbiorczego, podgląd, okres 08_14_09_2026"],
    ),
    "ostrzezenia-z-powtorzeniami": (
        {"result": "WYMAGA_SPRAWDZENIA", "messages": [warning("BRAK_MAPOWANIA"), warning("NIEZNANE_URZADZENIA"), warning("BRAK_MAPOWANIA")]},
        [
            "- Wynik: WYMAGA_SPRAWDZENIA",
            "- Komunikaty: `BRAK_MAPOWANIA` ×2 (ostrzeżenie), `NIEZNANE_URZADZENIA` (ostrzeżenie)",
        ],
    ),
    "zatrzymanie-do-maksa": (
        {"result": "BLAD_KRYTYCZNY", "ending": "stop", "stop_kind": "for_maks", "messages": [STOP]},
        ["- Wynik: BLAD_KRYTYCZNY, Zatrzymanie do Maksa", "- Komunikaty: `ZLA_KONFIGURACJA_WYKONAWCOW` (Zatrzymanie)"],
    ),
    "powtorka": (
        {"result": "BLAD_KRYTYCZNY", "ending": "stop", "stop_kind": "repeated", "messages": [STOP]},
        ["- Wynik: BLAD_KRYTYCZNY, powtórzone Zatrzymanie dla taty"],
    ),
    "nieoczekiwany-wyjatek": (
        {"result": "BLAD_KRYTYCZNY", "ending": "unexpected", "stop_kind": "for_maks", "duration_ms": None},
        ["- Wynik: BLAD_KRYTYCZNY, nieoczekiwany wyjątek", "- Czas: nieznany"],
    ),
    "po-silniku": (
        {"result": "BLAD_KRYTYCZNY", "ending": "after_engine", "stop_kind": "for_maks", "duration_ms": 12_345},
        ["- Wynik: BLAD_KRYTYCZNY, błąd po zakończeniu silnika", "- Czas: 12,3 s"],
    ),
    "bez-commitu": (
        {"tool": {"wydanie": None, "commit": None}},
        ["- Wydanie: brak, commit nieznany"],
    ),
}


@pytest.mark.parametrize(("changes", "lines"), SUMMARY_LINES.values(), ids=SUMMARY_LINES.keys())
def test_podsumowanie_nazywa_wynik_sposob_zakonczenia_i_kody_komunikatow(
    changes: dict[str, Any], lines: list[str]
) -> None:
    summary = summary_markdown(record(**changes)).splitlines()

    assert [line for line in lines if line not in summary] == []


def test_logi_w_jednym_komentarzu_maja_podsumowanie_i_json_bez_numeru_czesci() -> None:
    logs = record()

    post = logi_post(logs)

    [comment] = post.parts
    assert comment.startswith(summary_markdown(logs) + "\n\n<details><summary>Logi JSON</summary>\n")
    assert "część" not in comment
    assert sent_json(post.parts) == logs.text


def test_logi_ponad_limit_komentarza_dziela_sie_na_czesci_ktore_razem_daja_caly_json() -> None:
    logs = record(
        result="WYMAGA_SPRAWDZENIA",
        messages=[warning("BRAK_MAPOWANIA", f"Wiersz {row}: {'ż' * 300}") for row in range(600)],
    )
    assert len(logs.text) > 3 * COMMENT_LIMIT

    post = logi_post(logs)

    count = len(post.parts)
    assert count >= 4
    assert all(len(comment) <= COMMENT_LIMIT for comment in post.parts)
    assert post.parts[0].startswith(summary_markdown(logs))
    assert [f"Logi JSON, część {number}/{count}</summary>" in comment for number, comment in enumerate(post.parts, 1)] == [
        True
    ] * count
    assert all(RUN_ID in comment.split("<details>")[0] for comment in post.parts)
    assert sent_json(post.parts) == logs.text


def sent_json(comments: tuple[str, ...]) -> str:
    parts = [JSON_PART.search(comment) for comment in comments]
    assert all(parts), comments
    return "".join(part.group(1) for part in parts if part)
