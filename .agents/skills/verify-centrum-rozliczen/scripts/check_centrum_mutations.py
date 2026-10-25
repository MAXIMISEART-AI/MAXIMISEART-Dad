"""Show that the drive of verify-centrum-rozliczen fails on broken variants of Centrum.

Each mutation runs one feature of the whole verification on its own copy of the checkout
(``tools/mutacje.py``) and must make it fail. A mutation whose anchor text is no longer in its
file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

DAD_NOTES = Path("src/rozliczenia/centrum/dad_notes.py")
APP = Path("src/rozliczenia/centrum/app.py")
RUN_CARDS = Path("src/rozliczenia/centrum/run_cards.py")
TOOL_UPDATES = Path("src/rozliczenia/centrum/tool_updates.py")
KEYED_BOX = Path("src/rozliczenia/centrum/keyed_box.py")
OUTBOX = Path("src/rozliczenia/centrum/outbox.py")
WORKBOOK_FILES = Path("src/rozliczenia/workbook_files.py")
QUANTITIES_TO_FILL = Path("src/rozliczenia/quantities_to_fill.py")
SETTINGS = Path("src/rozliczenia/centrum/settings.py")
STOPS = Path("src/rozliczenia/centrum/stops.py")
RUN_VIEW = Path("src/rozliczenia/centrum/run_view.py")
RUNNER = ".agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py"
KARTA = (RUNNER, "--feature", "karta-z-logow")
UWAGA = (RUNNER, "--feature", "uwaga-taty")
AKTUALIZACJA = (RUNNER, "--feature", "aktualizacja")
ZGLOSZENIE = (RUNNER, "--feature", "zgloszenie")
UZUPELNIENIE = (RUNNER, "--feature", "uzupelnienie")
DIAGNOZA = (RUNNER, "--feature", "diagnoza")
PRZYGOTOWANIE = (RUNNER, "--feature", "przygotowanie-pliku-zbiorczego")
PRZEBIEG = (RUNNER, "--feature", "przebieg-rozliczen")

MUTATIONS = (
    Mutation(
        "po starcie Centrum bez ostatniego Uruchomienia",
        (
            Edit(
                APP,
                "        previous=cards.last(),\n",
                "        previous=None,\n",
            ),
        ),
        KARTA,
        "karta Uruchomienia ginie z zamknięciem Centrum",
    ),
    Mutation(
        "Urwane Uruchomienie bez karty",
        (Edit(RUN_CARDS, "            return self._interrupted(started)\n", "            return None\n"),),
        KARTA,
        "po starcie Centrum tata nie wie, że Uruchomienie urwało się w trakcie",
    ),
    Mutation(
        "komentarz z odnośnikiem do odrzuconych Logów nie powstaje",
        (
            Edit(
                DAD_NOTES,
                "        outbox.post(Post(target, period=None, run_id=run_id, header=None, parts=(_logs_gone(run_id),)))\n",
                "        pass\n",
            ),
        ),
        UWAGA,
        "Maks nie dostaje odnośnika do Logów, które dotarły po Uwadze",
    ),
    Mutation(
        "komentarz po odrzuconych Logach bez odnośnika",
        (
            Edit(
                DAD_NOTES,
                "            return replace(post, parts=(_logs_arrived(post.run_id, address),))\n",
                "            return post\n",
            ),
        ),
        UWAGA,
        "Maks dostaje komentarz, że Logi nie dotrą, choć dotarły",
    ),
    Mutation(
        "„nie dotarły” zamienione na „w drodze”",
        (Edit(DAD_NOTES, "        return _rejected_logs_line(run_id)\n", "        return _logs_line(run_id, None)\n"),),
        UWAGA,
        "wysłana Uwaga mówi, że Logi są w drodze, choć Skrzynka je odrzuciła",
    ),
    Mutation(
        "„nie powstały” zamienione na „nie dotarły”",
        (Edit(DAD_NOTES, "    if rejected(run_id):\n", "    if True:\n"),),
        UWAGA,
        "Uwaga obiecuje odnośnik do Logów, których nie ma w kolejce",
    ),
    Mutation(
        "wynik AKTUALNA zostaje, gdy najnowsze Wydanie to commit narzędzia",
        (
            Edit(
                TOOL_UPDATES,
                "            if newest is not None and newest != judged and self._view is view:\n",
                "            if newest is not None and newest != judged and newest.newest != self._commit() and self._view is view:\n",
            ),
        ),
        AKTUALIZACJA,
        "karta mówi „Masz najnowszą wersję.” o Wydaniu, którego Centrum już nie zna",
    ),
    Mutation(
        "odmowa Skrzynki nie odrzuca klucza",
        (
            Edit(
                KEYED_BOX,
                "            self._verdict = _Verdict(digest, isinstance(outcome, Refused), asked_at)\n",
                "            self._verdict = _Verdict(digest, False, asked_at)\n",
            ),
        ),
        ZGLOSZENIE,
        "Konfiguracja mówi „Zgłoszenia: gotowe” o kluczu, którego Skrzynka odmawia",
    ),
    Mutation(
        "kolejka nie ponawia wysyłki po porażce",
        (
            Edit(
                OUTBOX,
                "                    if self._stopped_on is not None and not self._retry_armed:\n",
                "                    if False:\n",
            ),
        ),
        ZGLOSZENIE,
        "Zgłoszenie bez sieci nie wysyła się samo po powrocie sieci",
    ),
    Mutation(
        "plik blokady Excela blokuje odczyt Uzupełnienia",
        (Edit(WORKBOOK_FILES, "    if open_in_excel and not despite_excel_lock:\n", "    if open_in_excel:\n"),),
        UZUPELNIENIE,
        "tata z Plikiem zbiorczym otwartym w Excelu widzi Komunikat zamiast swoich postępów",
    ),
    Mutation(
        "wpis taty nie robi wiersza",
        (Edit(QUANTITIES_TO_FILL, "    return any(order.quantity(column) != 0 for", "    return False and any(order.quantity(column) != 0 for"),),
        UZUPELNIENIE,
        "wiersz, który tata uzupełnił w Excelu, zostaje na liście do zrobienia",
    ),
    Mutation(
        "„Otwórz Rejestr zleceń” niczego nie otwiera",
        (Edit(SETTINGS, "        platform.open_path(register)\n", "        pass\n"),),
        DIAGNOZA,
        "tata klika „Otwórz Rejestr zleceń” przy Zatrzymaniu do poprawy, a Excel się nie otwiera",
    ),
    Mutation(
        "odmowa w Decyzji taty jak Zatrzymanie dla taty",
        (Edit(STOPS, '        if stop.kind == "declined":\n', "        if False:\n"),),
        PRZYGOTOWANIE,
        "karta pokazuje odmowę taty jako Zatrzymanie do poprawy zamiast spokojnego „Przerwano”",
    ),
    Mutation(
        "po Przebiegu rozliczeń akcją główną jest Plik zbiorczy",
        (Edit(RUN_VIEW, '    result_action="open_worker_settlements_folder",\n', '    result_action="open_collective_file",\n'),),
        PRZEBIEG,
        "po zapisie Rozliczeń pracowników karta proponuje otwarcie Pliku zbiorczego zamiast ich folderu",
    ),
    Mutation(
        "pusty szablon nie jest oznaczony",
        (Edit(RUN_VIEW, '                empty=result.status == "PUSTY_SZABLON",\n', "                empty=False,\n"),),
        PRZEBIEG,
        "Rozliczenie pracownika bez zleceń wygląda jak zapisane, bez oznaczenia „pusty”",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
