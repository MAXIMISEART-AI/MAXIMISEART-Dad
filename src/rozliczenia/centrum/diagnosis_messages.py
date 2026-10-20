"""Katalog Komunikatów Diagnozy: przyczyny, których nie opisuje żaden katalog procesu.

Diagnoza wyjaśnia przyczynę Komunikatem z katalogu procesu, gdy proces ma
własny (np. Rejestr zleceń otwarty w Excelu). Ten katalog ma tylko resztę:
brak przyczyny, plik okresu otwarty w Excelu i nieoczekiwany wyjątek w
dzienniku Centrum. Instrukcja taty cytuje „Co się stało” każdego Komunikatu
(``tests/test_instrukcja_taty.py``).
"""

from __future__ import annotations

from pathlib import Path

from rozliczenia.message import REPORT_TO_MAINTAINER, Message, file_label

_DIAGNOSIS = "Diagnoza w Centrum rozliczeń"


def cause_not_found() -> Message:
    """Każde sprawdzenie Diagnozy przeszło: przyczyna nie leży na komputerze taty."""

    return Message(
        code="NIE_ZNALEZIONO_PRZYCZYNY",
        what="Nie znalazłem przyczyny na tym komputerze.",
        where=_DIAGNOSIS,
        action="Wyślij do Maksa.",
    )


def period_file_open(path: Path) -> Message:
    """Plik okresu ma obok plik blokady Excela ``~$…``; narzędzie go nie usuwa."""

    return Message(
        code="PLIK_OKRESU_OTWARTY",
        what="Plik okresu jest otwarty w Excelu.",
        where=file_label(path),
        action=(
            "Zapisz i zamknij plik w Excelu, potem uruchom ponownie. Jeśli Excel jest zamknięty, "
            f"usuń z tego samego folderu pozostawiony plik ~${path.name} i uruchom ponownie."
        ),
    )


def unexpected_failure_logged() -> Message:
    """Dziennik Centrum od jego startu ma wpis o nieoczekiwanym wyjątku narzędzia."""

    return Message(
        code="WYJATEK_W_DZIENNIKU",
        what="W dzienniku Centrum rozliczeń jest nieoczekiwany wyjątek narzędzia.",
        where="dziennik Centrum rozliczeń",
        action=REPORT_TO_MAINTAINER,
    )
