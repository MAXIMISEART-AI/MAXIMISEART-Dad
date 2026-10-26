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
                "                for copy in copies:\n                    copy.unlink()\n",
                "                pass\n",
            ),
        ),
        EXPLORER,
        "Zatrzymanie przy INTERMAX otwartym w Excelu zostawia Kopię, choć INTERMAX się nie zmienił",
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
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
