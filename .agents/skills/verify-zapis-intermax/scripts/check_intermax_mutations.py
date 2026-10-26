"""Show that explore_intermax.py fails on broken variants of the INTERMAX save.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must end the checker's report with the
expected line. A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new
code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

ORDERING = Path("src/rozliczenia/intermax_ordering.py")
COPIES = Path("src/rozliczenia/intermax_copies.py")
FILE = Path("src/rozliczenia/intermax_file.py")
SAVE = Path("src/rozliczenia/workbook_save.py")
EXPLORER = (".agents/skills/verify-zapis-intermax/scripts/explore_intermax.py",)
NEW = "INTERMAX: NOWE NARUSZENIE"

MUTATIONS = (
    Mutation(
        "podmiana bez Kopii INTERMAX",
        (
            Edit(
                ORDERING,
                "            copies.append(intermax_copies.make_copy(register.content, copies_directory, now()))\n",
                "            pass\n",
            ),
        ),
        EXPLORER,
        "INTERMAX zmieniony bez Kopii, z której tata by go przywrócił",
        NEW,
    ),
    Mutation(
        "Kopia z innych bajtów niż przeczytane",
        (
            Edit(
                ORDERING,
                "intermax_copies.make_copy(register.content, copies_directory, now())",
                'intermax_copies.make_copy(b"", copies_directory, now())',
            ),
        ),
        EXPLORER,
        "Kopia INTERMAX nie przywraca stanu sprzed Uporządkowania",
        NEW,
    ),
    Mutation(
        "Kopia zostaje po nieudanej podmianie",
        (
            Edit(
                ORDERING,
                "            except WorkbookSaveError as error:\n                for copy in copies:\n                    copy.unlink()\n",
                "            except WorkbookSaveError as error:\n                pass\n",
            ),
        ),
        EXPLORER,
        "Zatrzymanie przy INTERMAX otwartym w Excelu zostawia Kopię, choć INTERMAX się nie zmienił",
        NEW,
    ),
    Mutation(
        "Kopia zostaje po odmowie OneDrive",
        (
            Edit(
                ORDERING,
                "            except HeldByOneDrive as error:\n                for copy in copies:\n                    copy.unlink()\n",
                "            except HeldByOneDrive as error:\n                pass\n",
            ),
        ),
        EXPLORER,
        "Zatrzymanie, bo OneDrive synchronizuje INTERMAX, zostawia Kopię, choć INTERMAX się nie zmienił",
        NEW,
    ),
    Mutation(
        "nieudane usunięcie starych Kopii wychodzi wyjątkiem",
        (
            Edit(
                ORDERING,
                "        except OSError:\n            warnings.append(messages.old_copies_kept(copies_directory))\n",
                "        except ValueError:\n            warnings.append(messages.old_copies_kept(copies_directory))\n",
            ),
        ),
        EXPLORER,
        "uporządkowany INTERMAX kończy się nieoczekiwanym błędem zamiast ostrzeżenia",
        NEW,
    ),
    Mutation(
        "plik tymczasowy zostaje po nieudanej podmianie",
        (
            Edit(
                SAVE,
                '            raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc\n    finally:\n        temporary_path.unlink(missing_ok=True)\n',
                '            raise WorkbookSaveError(f"Nie można zapisać skoroszytu: {target.name}") from exc\n    finally:\n        pass\n',
            ),
        ),
        EXPLORER,
        "obok INTERMAX w OneDrive zostaje plik tymczasowy",
        NEW,
    ),
    Mutation(
        "ponowna próba podmiany bez ponownego odczytu INTERMAX",
        (
            Edit(
                FILE,
                "            if not unchanged:\n                raise HeldByOneDrive(target.name)\n",
                "",
            ),
        ),
        EXPLORER,
        "zmiana pracownika, którą OneDrive wgrał, gdy odmówił podmiany, przepada przy ponownej próbie",
        NEW,
    ),
    Mutation(
        "ponowny odczyt INTERMAX przed przerwą zamiast po niej",
        (
            Edit(FILE, "            waiting.pause(_PAUSE_S)\n            try:\n", "            try:\n"),
            Edit(
                FILE,
                "            if not unchanged:\n                raise HeldByOneDrive(target.name)\n",
                "            if not unchanged:\n                raise HeldByOneDrive(target.name)\n            waiting.pause(_PAUSE_S)\n",
            ),
        ),
        EXPLORER,
        "zmiana pracownika, którą OneDrive wgrał w przerwie przed ponowną próbą, przepada przy tej próbie",
        NEW,
    ),
    Mutation(
        "stare Kopie sortowane odwrotnie",
        (
            Edit(
                COPIES,
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name), reverse=True)\n",
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name))\n",
            ),
        ),
        EXPLORER,
        "od 11. Uporządkowania keep_newest usuwa świeżą Kopię zaraz po podmianie",
        NEW,
    ),
    Mutation(
        "zostaje jedna Kopia zamiast KEPT",
        (
            Edit(
                COPIES,
                "    for copy in listed(directory)[KEPT:]:\n",
                "    for copy in listed(directory)[1:]:\n",
            ),
        ),
        EXPLORER,
        "tata ma jedną Kopię INTERMAX zamiast dziesięciu",
        NEW,
    ),
    Mutation(
        "Kopie ułożone po nazwie zamiast po chwili z nazwy",
        (
            Edit(
                COPIES,
                "    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name), reverse=True)\n",
                "    return sorted(copies, key=lambda copy: copy.path.name, reverse=True)\n",
            ),
        ),
        EXPLORER,
        "limit 10 usuwa świeże Kopie „przed przywróceniem”, bo ich nazwa stoi wcześniej w alfabecie",
        NEW,
    ),
    Mutation(
        "przywrócenie bez Kopii stanu bieżącego",
        (
            Edit(
                COPIES,
                '            made.append(make_copy(current, directory, moment, "restore"))\n',
                "            made.append(directory / \"brak\")\n",
            ),
        ),
        EXPLORER,
        "przywrócenie podmienia INTERMAX, a stanu sprzed niego nie ma w żadnej Kopii",
        NEW,
    ),
    Mutation(
        "Kopia stanu bieżącego zostaje po nieudanym przywróceniu",
        (
            Edit(
                COPIES,
                "        for path in made:\n            path.unlink()\n",
                "        pass\n",
            ),
        ),
        EXPLORER,
        "odmowa przywrócenia zostawia nową Kopię, choć INTERMAX się nie zmienił",
        NEW,
    ),
    Mutation(
        "przywrócenie podmienia INTERMAX bajtami sprzed przywrócenia",
        (
            Edit(
                COPIES,
                "        intermax_file.restore(register, current, content, before_replace=before_replace, waiting=waiting)\n",
                "        intermax_file.restore(register, current, current, before_replace=before_replace, waiting=waiting)\n",
            ),
        ),
        EXPLORER,
        "tata klika „Przywróć tę kopię”, a INTERMAX dalej ma zepsuty stan",
        NEW,
    ),
    Mutation(
        "nieudana podmiana usuwa wszystkie Kopie",
        (
            Edit(
                ORDERING,
                "            except WorkbookSaveError as error:\n                for copy in copies:\n                    copy.unlink()\n",
                "            except WorkbookSaveError as error:\n                for copy in list(copies_directory.iterdir()):\n                    copy.unlink()\n",
            ),
        ),
        EXPLORER,
        "Zatrzymanie przy INTERMAX otwartym w Excelu usuwa wcześniejsze Kopie taty",
        NEW,
    ),
    Mutation(
        "Kopia przed sprawdzeniem zapisu",
        (
            Edit(
                FILE,
                "        temporary.write_bytes(content)\n        try:\n",
                "        temporary.write_bytes(content)\n        before_replace()\n        try:\n",
            ),
            Edit(
                FILE,
                '            raise WriteMismatch("odczyt") from error\n        before_replace()\n',
                '            raise WriteMismatch("odczyt") from error\n',
            ),
        ),
        EXPLORER,
        "Zatrzymanie po niezgodnym zapisie zostawia Kopię INTERMAX",
        NEW,
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
