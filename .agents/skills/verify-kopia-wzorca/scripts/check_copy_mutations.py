"""Show that check_template_copy.py fails on broken variants of the template copy.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) with the
checker, without shrinking, and must end with ``KOPIA WZORCA: NOWE NARUSZENIE``. A
mutation whose anchor text is no longer in ``template_copy.py`` exactly once is
reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from mutacje import Edit, Mutation, check_all  # noqa: E402

VERIFIED = Path("src/rozliczenia/template_copy.py")
CHECKER = (".agents/skills/verify-kopia-wzorca/scripts/check_template_copy.py", "--no-shrink")
EXPECTED = "KOPIA WZORCA: NOWE NARUSZENIE"

MUTATIONS = (
    Mutation(
        "CRC arkusza tylko z początku",
        (Edit(VERIFIED, "crc = zlib.crc32(memoryview(xml)[tail_start:], zlib.crc32(head))", "crc = zlib.crc32(head)"),),
        CHECKER,
        "Excel i openpyxl odrzucają Rozliczenie pracownika jako uszkodzony plik",
        EXPECTED,
    ),
    Mutation(
        "kawałki kompresji bez pełnego opróżnienia",
        (Edit(VERIFIED, "compressor.flush(zlib.Z_FINISH if last else zlib.Z_FULL_FLUSH)", "compressor.flush(zlib.Z_FINISH if last else zlib.Z_SYNC_FLUSH)"),),
        CHECKER,
        "kawałek sięga wstecz do bajtów Wzorca, których po podmianie już nie ma: arkusz jest uszkodzony",
        EXPECTED,
    ),
    Mutation(
        "zgubiony kawałek za podmienionymi wierszami",
        (Edit(VERIFIED, "*self._chunks[chunk:]", "*self._chunks[chunk + 1 :]"),),
        CHECKER,
        "z Rozliczenia pracownika znika 64 wierszy Wzorca z formułami",
        EXPECTED,
    ),
    Mutation(
        "dimension bez wpisanych wierszy",
        (Edit(VERIFIED, "max(max_row or 1, last_row),", "max_row or 1,"),),
        CHECKER,
        "zakres arkusza nie obejmuje Wierszy danych za sformatowanymi wierszami Wzorca",
        EXPECTED,
    ),
    Mutation(
        "data bez formatu daty",
        (Edit(VERIFIED, "date_format = None if is_date_format(styles.number_format(template_style)) else _date_format(value)", "date_format = None"),),
        CHECKER,
        "data zlecenia pokazuje się jako liczba seryjna",
        EXPECTED,
    ),
    Mutation(
        "pusta wartość nie czyści zer Wzorca",
        (Edit(VERIFIED, 'if style == template_style and existing is not None and existing.endswith(b"/>"):', "if existing is not None:"),),
        CHECKER,
        "pusta ilość z Pliku zbiorczego zostaje w Rozliczeniu pracownika zerem z Wzorca",
        EXPECTED,
    ),
    Mutation(
        "Wyróżnienia bez wypełnienia",
        (Edit(VERIFIED, 'xf = _with_id(xf, b"fillId", fill_id, b"applyFill")', "pass"),),
        CHECKER,
        "wypełnienie komórki z Pliku zbiorczego nie przechodzi do Rozliczenia pracownika",
        EXPECTED,
    ),
    Mutation(
        "15 cyfr znaczących zamiast 16",
        (Edit(VERIFIED, '"%.16g"', '"%.15g"'),),
        CHECKER,
        "ilości i kwoty są zaokrąglone inaczej niż przy zapisie przez openpyxl",
        EXPECTED,
    ),
    Mutation(
        "xml:space tylko przy spacji na początku",
        (Edit(VERIFIED, "if text != text.strip() else", "if text != text.lstrip() else"),),
        CHECKER,
        "Excel ucina spacje na końcu tekstu",
        EXPECTED,
    ),
    Mutation(
        "& bez escapowania",
        (Edit(VERIFIED, 'text.replace("&", "&amp;")', "text"),),
        CHECKER,
        "tekst z & daje niepoprawny XML i plik, którego Excel nie otworzy",
        EXPECTED,
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
