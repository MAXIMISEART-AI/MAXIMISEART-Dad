"""Show that check_template_copy.py fails on broken variants of the template copy.

Each mutation is applied to a copy of ``src`` in a temporary directory, never to
the checkout. The checker then runs against that copy, without shrinking, and must
end with ``KOPIA WZORCA: NOWE NARUSZENIE``. A mutation whose anchor text is no
longer in ``template_copy.py`` exactly once is reported as NIEAKTUALNA: update it
to the new code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[3]
VERIFIED = Path("rozliczenia") / "template_copy.py"
CHECKER = SCRIPTS / "check_template_copy.py"
EXPECTED = "KOPIA WZORCA: NOWE NARUSZENIE"


@dataclass(frozen=True)
class Mutation:
    name: str
    harm: str
    anchor: str
    replacement: str


MUTATIONS = (
    Mutation(
        "CRC arkusza tylko z początku",
        "Excel i openpyxl odrzucają Rozliczenie pracownika jako uszkodzony plik",
        "crc = zlib.crc32(memoryview(xml)[tail_start:], zlib.crc32(head))",
        "crc = zlib.crc32(head)",
    ),
    Mutation(
        "kawałki kompresji bez pełnego opróżnienia",
        "kawałek sięga wstecz do bajtów Wzorca, których po podmianie już nie ma: arkusz jest uszkodzony",
        "compressor.flush(zlib.Z_FINISH if last else zlib.Z_FULL_FLUSH)",
        "compressor.flush(zlib.Z_FINISH if last else zlib.Z_SYNC_FLUSH)",
    ),
    Mutation(
        "zgubiony kawałek za podmienionymi wierszami",
        "z Rozliczenia pracownika znika 64 wierszy Wzorca z formułami",
        "*self._chunks[chunk:]",
        "*self._chunks[chunk + 1 :]",
    ),
    Mutation(
        "dimension bez wpisanych wierszy",
        "zakres arkusza nie obejmuje Wierszy danych za sformatowanymi wierszami Wzorca",
        "max(max_row or 1, last_row),",
        "max_row or 1,",
    ),
    Mutation(
        "data bez formatu daty",
        "data zlecenia pokazuje się jako liczba seryjna",
        "if not is_date_format(styles.number_format(style)):",
        "if False:",
    ),
    Mutation(
        "pusta wartość nie czyści zer Wzorca",
        "pusta ilość z Pliku zbiorczego zostaje w Rozliczeniu pracownika zerem z Wzorca",
        'if existing is not None and existing.endswith(b"/>"):',
        "if existing is not None:",
    ),
    Mutation(
        "15 cyfr znaczących zamiast 16",
        "ilości i kwoty są zaokrąglone inaczej niż przy zapisie przez openpyxl",
        '"%.16g"',
        '"%.15g"',
    ),
    Mutation(
        "xml:space tylko przy spacji na początku",
        "Excel ucina spacje na końcu tekstu",
        "if text != text.strip() else",
        "if text != text.lstrip() else",
    ),
    Mutation(
        "& bez escapowania",
        "tekst z & daje niepoprawny XML i plik, którego Excel nie otworzy",
        'text.replace("&", "&amp;")',
        "text",
    ),
)


def run_mutation(mutation: Mutation) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="kopia-wzorca-mutacja-") as scratch:
        source = Path(scratch) / "src"
        shutil.copytree(REPO_ROOT / "src", source, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        verified = source / VERIFIED
        code = verified.read_text(encoding="utf-8")
        if code.count(mutation.anchor) != 1:
            return False, "NIEAKTUALNA: kotwicy nie ma dokładnie raz w template_copy.py"
        verified.write_text(code.replace(mutation.anchor, mutation.replacement), encoding="utf-8")
        environment = {**os.environ, "VERIFY_KOPIA_SRC": str(source), "PYTHONUTF8": "1"}
        completed = subprocess.run(
            [sys.executable, str(CHECKER), "--no-shrink"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=600,
            check=False,
        )
    lines = completed.stdout.strip().splitlines()
    last = lines[-1] if lines else completed.stderr.strip()[-300:]
    return last.startswith(EXPECTED), last


def main() -> int:
    failures = 0
    for mutation in MUTATIONS:
        caught, last = run_mutation(mutation)
        failures += not caught
        verdict = "WYKRYTA" if caught else "NIEWYKRYTA"
        print(f"{verdict}: {mutation.name} ({mutation.harm}) → {last}", flush=True)
    print("MUTACJE OK" if not failures else f"MUTACJE: {failures} bez oczekiwanego wyniku")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
