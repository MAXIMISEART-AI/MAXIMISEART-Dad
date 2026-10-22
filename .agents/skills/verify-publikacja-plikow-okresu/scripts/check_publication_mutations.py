"""Show that explore_publication.py fails on broken variants of the publication code.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must
end the checker's report with the expected line. A mutation whose anchor text is no
longer in ``preparation_files.py`` is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from mutacje import Edit, Mutation, check_all  # noqa: E402

VERIFIED = Path("src/rozliczenia/preparation_files.py")
EXPLORER = (".agents/skills/verify-publikacja-plikow-okresu/scripts/explore_publication.py",)

MUTATIONS = (
    Mutation(
        "os.replace zamiast os.rename",
        (Edit(VERIFIED, "            os.rename(staged_directory / filename, target)\n", "            os.replace(staged_directory / filename, target)\n"),),
        EXPLORER,
        "plik taty o nazwie pliku okresu zostaje zastąpiony",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "bez wycofania opublikowanego pliku",
        (Edit(VERIFIED, "                target.unlink(missing_ok=True)\n", "                pass\n"),),
        EXPLORER,
        "po błędzie zostaje samo Rozliczenie wewnętrzne",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "nieudane wycofanie zgłaszane jak zwykły błąd zapisu",
        (Edit(VERIFIED, "                raise StopError(messages.write_failed_with_file_left(period_directory, target.name)) from exc\n", "                raise\n"),),
        EXPLORER,
        "zostaje Rozliczenie wewnętrzne, a komunikat mówi, że nie utworzono żadnego pliku",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "zapis na listę do wycofania przed os.rename",
        (Edit(VERIFIED, "            os.rename(staged_directory / filename, target)\n            published.append(target)\n", "            published.append(target)\n            os.rename(staged_directory / filename, target)\n"),),
        EXPLORER,
        "wycofanie usuwa plik taty",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "błąd sprzątania katalogu tymczasowego jako błąd zapisu",
        (Edit(VERIFIED, ", ignore_cleanup_errors=True\n", "\n"),),
        EXPLORER,
        "oba pliki okresu są w Folderze okresu, a komunikat mówi, że nie utworzono żadnego pliku",
        "PUBLIKACJA: NOWE NARUSZENIE",
    ),
    Mutation(
        "shutil.move zamiast os.rename",
        (Edit(VERIFIED, "            os.rename(staged_directory / filename, target)\n", "            __import__('shutil').move(staged_directory / filename, target)\n"),),
        EXPLORER,
        "przy zajętej nazwie shutil.move kopiuje plik i nadpisuje cel",
        "PUBLIKACJA: LUKA MODELU",
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
