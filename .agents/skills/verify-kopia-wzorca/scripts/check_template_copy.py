"""Check that the Rozliczenie pracownika made by the template copy (ADR 0008) is the one openpyxl would make.

Przebieg rozliczeń writes every Rozliczenie pracownika with ``template_copy.py``: it splices the
Wiersze danych into the bytes of the Wzorzec rozliczenia pracownika instead of loading and saving the
workbook with openpyxl. This checker generates Wiersze danych with Hypothesis (every value type a cell
can hold, edge texts and numbers, row counts on both sides of each compression chunk boundary), writes
them through the real ``WorkerSettlementTemplate.create_settlement()`` and, as the reference, through
the old openpyxl path (``file_from_template`` + ``write_data_rows``), and checks four rules:

- WIERNA_KOPIA: the two files are the same for what Dad sees in Excel, as judged by the benchmark's
  correctness gate (``tools/porownanie_rozliczen.py``): values, formulas, resolved styles, merges,
  dimensions, defined names, external links and recalculation flags.
- TA_SAMA_ODMOWA: the copy refuses a value exactly when the openpyxl path refuses it, and a refusal
  leaves no file.
- NIETKNIETY_WZORZEC: what ADR 0008 says stays byte for byte stays: every zip part except the sheet,
  ``xl/workbook.xml`` (only ``calcPr``) and ``xl/styles.xml`` (only appended styles), every sheet row
  outside the written Wiersze danych, and the cells right of AT in the written rows.
- KSZTALT_EXCELA: the file has the shape Excel needs and openpyxl does not check when reading it:
  valid zip CRCs, rows and cells in ascending order with matching references, ``dimension`` covering
  the written rows, ``xml:space="preserve"`` on text with spaces at its edges, style counts that match.

One Hypothesis example is one Przebieg rozliczeń: one ``WorkerSettlementTemplate`` loaded once and
1 to 3 Rozliczenia pracowników made from it in a row, as ``run_settlements()`` does for its workers.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import time as clock
import warnings
import zipfile
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[4]
# check_copy_mutations.py points this at a mutated copy of src; otherwise the checkout's own src is checked.
SOURCE_ROOT = Path(os.environ.get("VERIFY_KOPIA_SRC", REPO_ROOT / "src"))
sys.path[:0] = [str(SOURCE_ROOT), str(REPO_ROOT / "tools"), str(REPO_ROOT)]

from hypothesis import HealthCheck, Phase, example, given, seed, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.internal.conjecture import engine as hypothesis_engine  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from openpyxl.cell.rich_text import CellRichText, TextBlock  # noqa: E402
from openpyxl.cell.text import InlineFont  # noqa: E402
from openpyxl.utils import column_index_from_string, get_column_letter  # noqa: E402
from openpyxl.worksheet.formula import ArrayFormula  # noqa: E402

import porownanie_rozliczen as gate  # noqa: E402
from rozliczenia import workbook_files  # noqa: E402
from rozliczenia.workbook_files import ExcelRow, Layout, WorkerSettlementTemplate, file_from_template  # noqa: E402
from syntetyczne_wzorce import write_settlement_template  # noqa: E402
from tests.fixtures.settlement import write_template  # noqa: E402
from tests.fixtures.workbooks import add_external_link_fixture  # noqa: E402

VERIFIED_FILE = "template_copy.py"
SHEET = "xl/worksheets/sheet1.xml"
WORKBOOK = "xl/workbook.xml"
STYLES = "xl/styles.xml"
FIRST_DATA_ROW = workbook_files.FIRST_DATA_ROW
DATA_COLUMNS = workbook_files.DATA_ROW_COLUMNS[-1]  # AT
ROWS_PER_CHUNK = 64  # Excel's shared-formula block and the copy's compression chunk (``_ROWS_PER_CHUNK``)
DEFAULT_EXAMPLES = 60
# Hypothesis shrinks a counterexample for up to 300 s; a minute gives a short story here and keeps a failing run cheap.
SHRINK_SECONDS = 60
CELL_DIFFERENCES_SHOWN = 5

# A known finding is a real divergence in the current code. It is printed with its first example on every
# run and does not fail the check until the code is fixed; then the checker stops seeing it and the entry
# is deleted here and in SKILL.md.
KNOWN_FINDINGS: dict[str, str] = {
    "PUSTA_KOMORKA_BEZ_STYLU_KOLUMNY": (
        "Pusta wartość w komórce, której nie ma w XML Wzorca (u taty A i B od wiersza 609), staje się w kopii "
        'komórką <c r=".."/> bez stylu; openpyxl jej nie zapisuje, więc Excel pokazuje tam styl kolumny.'
    ),
}

_ROW = re.compile(rb'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', re.S)
_CELL = re.compile(rb'<c r="([A-Z]{1,3})(\d+)"([^>]*?)(/>|>.*?</c>)', re.S)
_DIMENSION = re.compile(rb'<dimension ref="([^"]*)"\s*/>')
_CALC_PR = re.compile(rb"<(?:[\w.-]+:)?calcPr\b[^>]*?/?>")
_CELL_XFS = re.compile(rb"<cellXfs\b[^>]*>(.*?)</cellXfs>", re.S)
_NUM_FMTS = re.compile(rb"<numFmts\b[^>]*?(?:/>|>(.*?)</numFmts>)", re.S)
_COUNT = re.compile(rb'\scount="(\d+)"')
_XF = re.compile(rb"<xf\b[^>]*?(?:/>|>.*?</xf>)", re.S)
_NUM_FMT_ID = re.compile(rb'<numFmt\b[^>]*numFmtId="(\d+)"')
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# --- Wzorce ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    """A Wzorzec rozliczenia pracownika under test, with what the checker needs to know about its sheet."""

    name: str
    description: str
    path: Path
    content: bytes
    cells: frozenset[tuple[int, int]]  # (row, column) of every cell element in the sheet XML
    chunk_rows: tuple[int, ...]  # sheet rows within reach where a compressed chunk of the copy starts
    last_row: int  # last row of the sheet XML
    max_rows: int  # bound on Wiersze danych per Rozliczenie pracownika

    @classmethod
    def of(cls, name: str, description: str, path: Path, max_rows: int | None = None) -> Template:
        content = path.read_bytes()
        xml = zipfile.ZipFile(path).read(SHEET)
        rows = [int(match.group(1)) for match in _ROW.finditer(xml)]
        data_rows = [number for number in rows if number >= FIRST_DATA_ROW]
        cells = frozenset((int(match.group(2)), column_index_from_string(match.group(1).decode())) for match in _CELL.finditer(xml))
        last_row = rows[-1] if rows else 0
        bound = max_rows if max_rows is not None else max(last_row - FIRST_DATA_ROW + 1, 0) + 10
        # Chunk starts a Rozliczenie pracownika within the bound can reach; later ones only hold Wzorzec rows.
        chunk_rows = tuple(row for row in data_rows[::ROWS_PER_CHUNK] if row <= FIRST_DATA_ROW + bound)
        return cls(name, description, path, content, cells, chunk_rows, last_row, bound)

    def interesting_counts(self) -> list[int]:
        """Row counts whose last written row is right before, on, or right after a chunk start or the sheet end."""

        edges = [*self.chunk_rows, self.last_row, self.last_row + 1]
        counts = {0, 1, self.max_rows}
        for row in edges:
            counts.update(row - FIRST_DATA_ROW + offset for offset in (0, 1, 2))
        return sorted(count for count in counts if 0 <= count <= self.max_rows)


def build_templates(directory: Path, real_template: Path | None) -> list[Template]:
    """The synthetic Wzorce, or only Dad's real Wzorzec when it is given."""

    if real_template is not None:
        copied = directory / "wzorzec-taty.xlsx"
        shutil.copyfile(real_template, copied)
        return [Template.of("wzorzec-taty", f"prawdziwy Wzorzec: {real_template.name}", copied, max_rows=700)]
    synthetic = directory / "syntetyczny.xlsx"
    write_settlement_template(synthetic, "GODZINA", data_rows=200)
    small = directory / "maly.xlsx"
    write_template(small)
    add_external_link_fixture(small)
    templates = [
        Template.of(
            "syntetyczny",
            "kształt Wzorca taty z tools/syntetyczne_wzorce.py, 200 Wierszy danych: wspólne formuły, calcChain, "
            "link zewnętrzny, wiersze zer w N:V i X, A i B bez komórek od wiersza 139",
            synthetic,
            max_rows=260,
        ),
        Template.of("maly", "skoroszyt zapisany przez openpyxl, dwa sformatowane Wiersze danych, drugi arkusz", small, max_rows=80),
    ]
    return templates


# --- Wiersze danych ---------------------------------------------------------------------------------

EDGE_TEXTS = (
    "",
    " ",
    "=",
    "==",
    "=N18*2",
    '="a<b&c"',
    "#N/A",
    "#DIV/0!",
    "#ARG!",
    " spacja na początku",
    "spacja na końcu ",
    "\tz tabulatorem",
    "linia 1\nlinia 2",
    "linia 1\r\nlinia 2\r",
    "_x000D_",
    '<b>&amp; "cudzysłów" \'apostrof\' ]]></b>',
    "zażółć gęślą jaźń ŻÓŁĆ",
    "😀 poza BMP",
    " twarda spacja ",
    "a" * 32767,
    "b" * 32767 + "ucięte",
)
EDGE_NUMBERS: tuple[int | float | Decimal, ...] = (
    0,
    -0.0,
    1,
    -1,
    2**53 + 1,
    10**16,
    -(10**20),
    0.1,
    1 / 3,
    1e-300,
    5e-324,
    1.7976931348623157e308,
    123456789.12345679,
    float("nan"),
    float("inf"),
    float("-inf"),
    Decimal("2.5"),
    Decimal("0.1000000000000000055511151231257827"),
    Decimal("-Infinity"),
)
EDGE_DATES: tuple[date | datetime | time | timedelta, ...] = (
    date(1900, 1, 1),
    date(1900, 2, 28),
    date(1900, 3, 1),
    date(1899, 12, 30),
    date(2026, 9, 8),
    datetime(2026, 9, 8, 7, 30, 15),
    datetime(2026, 9, 8, 23, 59, 59, 999999),
    datetime(1900, 2, 28, 12),
    time(0, 0),
    time(13, 45),
    time(23, 59, 59, 999999),
    timedelta(0),
    timedelta(hours=36, minutes=5),
    timedelta(days=-1, seconds=1),
)


def cell_values() -> st.SearchStrategy[object]:
    """Every value a Wiersz danych cell can hold: what Plik zbiorczy reading gives, and what openpyxl accepts."""

    printable = st.characters(exclude_categories=("Cs", "Cc"), include_characters="\t\n\r")
    texts = st.one_of(
        st.sampled_from(EDGE_TEXTS), st.text(printable, max_size=40), st.text(alphabet="=#<>&\"' \n\r\t_x0D", max_size=12)
    )
    numbers = st.one_of(
        st.sampled_from(EDGE_NUMBERS),
        st.integers(min_value=-(2**70), max_value=2**70),
        st.floats(),
        st.decimals(allow_nan=False, allow_infinity=True),
    )
    dates = st.one_of(st.sampled_from(EDGE_DATES), st.datetimes(), st.dates(), st.times(), st.timedeltas())
    common = st.one_of(st.none(), texts, numbers, st.booleans(), dates)
    # Values that make a path refuse the whole Rozliczenie pracownika or send it the old openpyxl way. They are
    # rare, so that most Rozliczenia pracowników of a run still go through the copy.
    rare = st.one_of(
        st.text(st.characters(max_codepoint=0x1F, exclude_characters="\t\n\r"), min_size=1, max_size=3),
        st.sampled_from((Decimal("NaN"), Decimal("sNaN"))),
        st.datetimes(timezones=st.just(timezone.utc)),
        st.times(timezones=st.just(timezone.utc)),
        st.sampled_from(
            (
                CellRichText("zwykły ", TextBlock(InlineFont(b=True), "pogrubiony")),
                ArrayFormula("Z1", "=SUM(N18:N19)"),
                b"bajty",
            )
        ),
    )
    return st.integers(min_value=0, max_value=59).flatmap(lambda pick: rare if pick == 0 else common)


@st.composite
def data_rows(draw: st.DrawFn, columns: int = DATA_COLUMNS) -> ExcelRow:
    """One Wiersz danych: usually 46 values (A:AT) as from Plik zbiorczy, sometimes shorter or longer."""

    width = draw(st.one_of(st.just(columns), st.integers(min_value=0, max_value=columns + 4)))
    values: dict[int, object] = draw(
        st.dictionaries(st.integers(min_value=0, max_value=max(width - 1, 0)), cell_values(), max_size=8)
    )
    if draw(st.booleans()):
        values.update({index: None for index in draw(st.lists(st.integers(min_value=0, max_value=max(width - 1, 0)), max_size=6))})
    return tuple(values.get(index) for index in range(width))  # type: ignore[misc]


@st.composite
def settlements(draw: st.DrawFn, template: Template) -> list[ExcelRow]:
    """Wiersze danych of one Rozliczenie pracownika: a few distinct rows repeated, with some rows overridden."""

    interesting = template.interesting_counts()
    count = draw(st.one_of(st.sampled_from(interesting), st.integers(min_value=0, max_value=template.max_rows)))
    palette = draw(st.lists(data_rows(), min_size=1, max_size=4))
    overrides = draw(st.dictionaries(st.integers(min_value=0, max_value=max(count - 1, 0)), data_rows(), max_size=3)) if count else {}
    return [overrides.get(index, palette[index % len(palette)]) for index in range(count)]


@dataclass(frozen=True)
class Case:
    """One Przebieg rozliczeń: one Wzorzec loaded once, then each Rozliczenie pracownika in order."""

    template: Template
    workers: tuple[tuple[ExcelRow, ...], ...]

    def __repr__(self) -> str:
        return f"Case({self.template.name}, {[len(rows) for rows in self.workers]} Wierszy danych)"


def cases(template: Template) -> st.SearchStrategy[Case]:
    return st.lists(settlements(template), min_size=1, max_size=3).map(
        lambda workers: Case(template, tuple(tuple(rows) for rows in workers))
    )


# --- one Rozliczenie pracownika --------------------------------------------------------------------


@dataclass(frozen=True)
class Divergence:
    rule: str
    detail: str
    known: str | None = None  # KNOWN_FINDINGS key, when the divergence is a known finding


@dataclass(frozen=True)
class Attempt:
    path: Path
    refusal: str | None  # exception type name, or None when the file was written


def _attempt(target: Path, write: Callable[[], None]) -> Attempt:
    try:
        write()
    except Exception as exc:  # noqa: BLE001 - both paths may refuse a value in any way; the type is compared
        return Attempt(target, type(exc).__name__)
    return Attempt(target, None)


def _write_with_openpyxl(template: Path, target: Path, rows: Sequence[ExcelRow]) -> None:
    with file_from_template(template, target, Layout.COLLECTIVE, recalculate=True) as sheet:
        sheet.write_data_rows(rows)


class Routes:
    """Which path ``create_settlement`` took: the copy, or the old openpyxl path (``_create_with_openpyxl``)."""

    def __init__(self) -> None:
        self.fallbacks: list[Path] = []
        original = WorkerSettlementTemplate._create_with_openpyxl

        def recording(worker: WorkerSettlementTemplate, target: Path, rows: Sequence[ExcelRow]) -> None:
            self.fallbacks.append(target)
            original(worker, target, rows)

        setattr(WorkerSettlementTemplate, "_create_with_openpyxl", recording)


@dataclass
class Statistics:
    examples: int = 0
    settlements: Counter[str] = field(default_factory=Counter)  # kopia / droga openpyxl / odmowa
    refusals: Counter[str] = field(default_factory=Counter)
    max_rows: int = 0
    chunk_rows_reached: set[int] = field(default_factory=set)


def check_settlement(
    template: Template, copy: Attempt, reference: Attempt, rows: Sequence[ExcelRow], via_copy: bool
) -> list[Divergence]:
    if copy.refusal is not None or reference.refusal is not None:
        found = []
        if (copy.refusal is None) != (reference.refusal is None):
            found.append(
                Divergence(
                    "TA_SAMA_ODMOWA",
                    f"kopia: {copy.refusal or 'zapisała plik'}, droga openpyxl: {reference.refusal or 'zapisała plik'}",
                )
            )
        leftovers = sorted(path.name for path in copy.path.parent.iterdir()) if copy.refusal is not None else []
        if leftovers:
            found.append(Divergence("TA_SAMA_ODMOWA", f"po odmowie zostały pliki: {leftovers}"))
        return found
    if via_copy:
        try:
            shape = _excel_shape_divergences(copy.path, len(rows))
        except Exception as exc:  # noqa: BLE001 - a file that cannot be read is the divergence itself
            return [Divergence("KSZTALT_EXCELA", f"pliku nie da się przeczytać: {type(exc).__name__}: {exc}")]
        if shape:
            return shape
        return _gate_divergences(template, copy.path, reference.path, rows) + _untouched_divergences(
            template, copy.path, len(rows)
        )
    return _gate_divergences(template, copy.path, reference.path, rows)


def _gate_divergences(template: Template, copy: Path, reference: Path, rows: Sequence[ExcelRow]) -> list[Divergence]:
    differences = gate.compare_worker_settlements(reference.parent, copy.parent)
    if not any(differences.values()):
        return []
    found: list[Divergence] = []
    cell_counts = Counter({category: differences[category] for category in ("wartosci", "formuly", "style")})
    other = {category: count for category, count in differences.items() if count and category not in cell_counts}
    if other:
        found.append(Divergence("WIERNA_KOPIA", f"bramka poprawności: {other}"))
    if sum(cell_counts.values()):
        unknown, known = _cell_differences(template, copy, reference, len(rows))
        if known:
            found.append(
                Divergence(
                    "WIERNA_KOPIA",
                    f"{len(known)} komórek, np. {', '.join(known[:CELL_DIFFERENCES_SHOWN])}",
                    known="PUSTA_KOMORKA_BEZ_STYLU_KOLUMNY",
                )
            )
        if unknown or len(known) != sum(cell_counts.values()):
            shown = "; ".join(unknown[:CELL_DIFFERENCES_SHOWN]) or f"liczniki bramki {dict(cell_counts)}"
            found.append(Divergence("WIERNA_KOPIA", f"{len(unknown)} komórek: {shown}"))
    return found


def _cell_differences(template: Template, copy: Path, reference: Path, written: int) -> tuple[list[str], list[str]]:
    """Cells that differ, with the gate's own semantics, split into new ones and the known finding."""

    reference_book, copy_book = load_workbook(reference), load_workbook(copy)
    copy_xml = zipfile.ZipFile(copy).read(SHEET)
    styles = gate._Styles()
    unknown: list[str] = []
    known: list[str] = []
    for title in dict.fromkeys([*reference_book.sheetnames, *copy_book.sheetnames]):
        expected, actual = gate._sheet(reference_book, title), gate._sheet(copy_book, title)
        expected_columns, actual_columns = gate._column_dimensions(expected), gate._column_dimensions(actual)
        for coordinate in sorted(expected._cells.keys() | actual._cells.keys()):
            row, column = coordinate
            expected_cell, actual_cell = expected._cells.get(coordinate), actual._cells.get(coordinate)
            label = f"{title}!{get_column_letter(column)}{row}"
            expected_formula, actual_formula = gate._formula(expected_cell), gate._formula(actual_cell)
            if expected_formula is not None or actual_formula is not None:
                if expected_formula != actual_formula:
                    unknown.append(f"{label} formuła kopia={_value_text(actual_formula)} openpyxl={_value_text(expected_formula)}")
                continue
            expected_value, actual_value = gate._value(expected_cell), gate._value(actual_cell)
            if expected_value != actual_value:
                unknown.append(f"{label} wartość kopia={_value_text(actual_value)} openpyxl={_value_text(expected_value)}")
            expected_style = gate._style(expected, expected_cell, coordinate, expected_columns, styles)
            actual_style = gate._style(actual, actual_cell, coordinate, actual_columns, styles)
            if expected_style == actual_style:
                continue
            reference_xml = f'<c r="{get_column_letter(column)}{row}"/>'.encode()
            if (
                title == copy_book.active.title  # type: ignore[union-attr]
                and expected_value is None
                and actual_value is None
                and column <= DATA_COLUMNS
                and FIRST_DATA_ROW <= row < FIRST_DATA_ROW + written
                and coordinate not in template.cells
                and reference_xml in copy_xml
            ):
                known.append(label)
            else:
                unknown.append(f"{label} styl (czcionka, wypełnienie, obramowanie, wyrównanie albo format liczb)")
    reference_book.close()
    copy_book.close()
    return unknown, known


def _rows(xml: bytes) -> dict[int, tuple[int, int]]:
    return {int(match.group(1)): match.span() for match in _ROW.finditer(xml)}


def _start_tag(row_xml: bytes) -> bytes:
    tag = row_xml[: row_xml.index(b">")]
    return tag.rstrip(b"/ ")


def _cells_right_of_data(row_xml: bytes) -> dict[int, bytes]:
    return {
        column_index_from_string(match.group(1).decode()): match.group(0)
        for match in _CELL.finditer(row_xml)
        if column_index_from_string(match.group(1).decode()) > DATA_COLUMNS
    }


def _without_calc_pr(xml: bytes) -> bytes:
    return _CALC_PR.sub(b"", xml, count=1)


def _without_style_lists(xml: bytes) -> bytes:
    return _NUM_FMTS.sub(b"", _CELL_XFS.sub(b"", xml, count=1), count=1)


def _untouched_divergences(template: Template, copy: Path, written: int) -> list[Divergence]:
    found: list[Divergence] = []
    original, result = zipfile.ZipFile(template.path), zipfile.ZipFile(copy)
    if [info.filename for info in original.infolist()] != [info.filename for info in result.infolist()]:
        return [Divergence("NIETKNIETY_WZORZEC", "inny zestaw albo kolejność części zip niż we Wzorcu")]
    for before in original.infolist():
        after = result.getinfo(before.filename)
        name = before.filename
        if name == SHEET:
            continue
        if name == WORKBOOK:
            if _without_calc_pr(original.read(name)) != _without_calc_pr(result.read(name)):
                found.append(Divergence("NIETKNIETY_WZORZEC", f"{name} zmienił się poza calcPr"))
            continue
        if name == STYLES:
            if _without_style_lists(original.read(name)) != _without_style_lists(result.read(name)):
                found.append(Divergence("NIETKNIETY_WZORZEC", f"{name} zmienił się poza cellXfs i numFmts"))
            xfs_before = _XF.findall(_CELL_XFS.search(original.read(name)).group(1))  # type: ignore[union-attr]
            xfs_after = _XF.findall(_CELL_XFS.search(result.read(name)).group(1))  # type: ignore[union-attr]
            if xfs_after[: len(xfs_before)] != xfs_before:
                found.append(Divergence("NIETKNIETY_WZORZEC", f"{name}: style Wzorca zmienione, a nie tylko dopisane"))
            continue
        same = (before.CRC, before.compress_size, before.compress_type) == (after.CRC, after.compress_size, after.compress_type)
        if not same or original.read(name) != result.read(name):
            found.append(Divergence("NIETKNIETY_WZORZEC", f"{name} nie jest przepisana bajt w bajt"))
    found += _sheet_untouched(original.read(SHEET), result.read(SHEET), written)
    return found


def _region(xml: bytes, rows: dict[int, tuple[int, int]], last: int) -> tuple[int, int]:
    """Span of the rows from the first Wiersz danych to ``last``; empty span where the first one would start."""

    inside = [span for number, span in rows.items() if FIRST_DATA_ROW <= number <= last]
    if inside:
        return inside[0][0], inside[-1][1]
    later = [span[0] for number, span in rows.items() if number > last]
    position = later[0] if later else xml.index(b"</sheetData>")
    return position, position


def _sheet_untouched(before: bytes, after: bytes, written: int) -> list[Divergence]:
    last = FIRST_DATA_ROW + written - 1
    rows_before, rows_after = _rows(before), _rows(after)
    start_before, end_before = _region(before, rows_before, last)
    start_after, end_after = _region(after, rows_after, last)
    found: list[Divergence] = []
    if _DIMENSION.sub(b"", before[:start_before]) != _DIMENSION.sub(b"", after[:start_after]):
        found.append(Divergence("NIETKNIETY_WZORZEC", "arkusz zmienił się przed pierwszym Wierszem danych"))
    if before[end_before:] != after[end_after:]:
        found.append(Divergence("NIETKNIETY_WZORZEC", f"arkusz zmienił się za ostatnim wpisanym wierszem {last}"))
    for number in range(FIRST_DATA_ROW, last + 1):
        if number not in rows_after:
            found.append(Divergence("NIETKNIETY_WZORZEC", f"brak wiersza {number} w arkuszu"))
            break
        if number not in rows_before:
            continue
        row_before = before[slice(*rows_before[number])]
        row_after = after[slice(*rows_after[number])]
        if _start_tag(row_before) != _start_tag(row_after):
            found.append(Divergence("NIETKNIETY_WZORZEC", f"atrybuty wiersza {number} zmienione"))
            break
        if _cells_right_of_data(row_before) != _cells_right_of_data(row_after):
            found.append(Divergence("NIETKNIETY_WZORZEC", f"komórki za AT w wierszu {number} nie są bajt w bajt"))
            break
    return found


def _excel_shape_divergences(copy: Path, written: int) -> list[Divergence]:
    found: list[Divergence] = []
    archive = zipfile.ZipFile(copy)
    broken = archive.testzip()
    if broken is not None:
        return [Divergence("KSZTALT_EXCELA", f"zła suma CRC części {broken}")]
    for name in archive.namelist():
        if name.endswith((".xml", ".rels")):
            ElementTree.fromstring(archive.read(name))
    names = archive.namelist()
    if len(names) != len(set(names)):
        found.append(Divergence("KSZTALT_EXCELA", "powtórzona część zip"))
    xml = archive.read(SHEET)
    root = ElementTree.fromstring(xml)
    previous_row = 0
    max_row, max_column = 0, 0
    for row in root.iter(f"{_MAIN}row"):
        number = int(row.get("r", "0"))
        if number <= previous_row:
            found.append(Divergence("KSZTALT_EXCELA", f"wiersz {number} po wierszu {previous_row}"))
        previous_row = number
        previous_column = 0
        for cell in row.iter(f"{_MAIN}c"):
            match = re.fullmatch(r"([A-Z]{1,3})(\d+)", cell.get("r", ""))
            if match is None or int(match.group(2)) != number:
                found.append(Divergence("KSZTALT_EXCELA", f"komórka {cell.get('r')} w wierszu {number}"))
                continue
            column = column_index_from_string(match.group(1))
            if column <= previous_column:
                found.append(Divergence("KSZTALT_EXCELA", f"komórka {cell.get('r')} nie rośnie w wierszu {number}"))
            previous_column = column
            if FIRST_DATA_ROW <= number < FIRST_DATA_ROW + written:
                max_row, max_column = max(max_row, number), max(max_column, column)
        if len(found) > CELL_DIFFERENCES_SHOWN:
            break
    for text in root.iter(f"{_MAIN}t"):
        value = text.text or ""
        if value != value.strip() and text.get(_XML_SPACE) != "preserve":
            found.append(Divergence("KSZTALT_EXCELA", f"tekst ze spacją na brzegu bez xml:space=\"preserve\": {value[:20]!r}"))
            break
    dimension = _DIMENSION.search(xml)
    if dimension is not None and written:
        reference = dimension.group(1).decode()
        last_cell = reference.split(":")[-1]
        bound = re.fullmatch(r"([A-Z]+)(\d+)", last_cell)
        if bound is None or int(bound.group(2)) < FIRST_DATA_ROW + written - 1 or column_index_from_string(bound.group(1)) < max_column:
            found.append(Divergence("KSZTALT_EXCELA", f"dimension {reference} nie obejmuje wpisanych wierszy do {FIRST_DATA_ROW + written - 1}"))
    styles = archive.read(STYLES)
    cell_xfs = re.search(rb"<cellXfs\b[^>]*>", styles)
    block = _CELL_XFS.search(styles)
    if cell_xfs is not None and block is not None:
        count = _COUNT.search(cell_xfs.group(0))
        xfs = len(_XF.findall(block.group(1)))
        if count is not None and int(count.group(1)) != xfs:
            found.append(Divergence("KSZTALT_EXCELA", f"cellXfs count={count.group(1).decode()}, a stylów jest {xfs}"))
        used = [int(style) for style in re.findall(rb'<c r="[A-Z]+\d+" s="(\d+)"', xml)]
        if used and max(used) >= xfs:
            found.append(Divergence("KSZTALT_EXCELA", f"komórka ze stylem {max(used)} spoza {xfs} stylów"))
    formats = [int(number) for number in _NUM_FMT_ID.findall(styles)]
    if len(formats) != len(set(formats)):
        found.append(Divergence("KSZTALT_EXCELA", "powtórzony numFmtId"))
    return found


# --- one Przebieg rozliczeń ------------------------------------------------------------------------


class Violation(AssertionError):
    def __init__(self, case: Case, divergences: list[tuple[int, Divergence]]) -> None:
        super().__init__(f"{case!r}: {[divergence.rule for _, divergence in divergences]}")
        self.case = case
        self.divergences = divergences


@dataclass
class Run:
    routes: Routes
    statistics: dict[str, Statistics]
    known: dict[str, tuple[Case, int, Divergence]] = field(default_factory=dict)

    def check(self, case: Case) -> None:
        template = case.template
        statistics = self.statistics[template.name]
        statistics.examples += 1
        divergences: list[tuple[int, Divergence]] = []
        with tempfile.TemporaryDirectory(prefix="kopia-wzorca-") as scratch:
            worker = WorkerSettlementTemplate(template.path)
            worker.check()
            for index, rows in enumerate(case.workers, start=1):
                copy_folder, reference_folder = Path(scratch) / f"kopia-{index}", Path(scratch) / f"openpyxl-{index}"
                copy_folder.mkdir()
                reference_folder.mkdir()
                name = f"Rozliczenie 08_14_09_2026 - Wykonawca {index}.xlsx"
                fallbacks = len(self.routes.fallbacks)
                copy = _attempt(copy_folder / name, lambda: worker.create_settlement(copy_folder / name, rows))
                via_copy = len(self.routes.fallbacks) == fallbacks
                reference = _attempt(reference_folder / name, lambda: _write_with_openpyxl(template.path, reference_folder / name, rows))
                route = "odmowa" if copy.refusal else "kopia" if via_copy else "droga openpyxl"
                statistics.settlements[route] += 1
                if copy.refusal:
                    statistics.refusals[copy.refusal] += 1
                statistics.max_rows = max(statistics.max_rows, len(rows))
                if via_copy and copy.refusal is None:
                    last = FIRST_DATA_ROW + len(rows) - 1
                    statistics.chunk_rows_reached.update(row for row in template.chunk_rows[1:] if row <= last + 1)
                divergences += [(index, divergence) for divergence in check_settlement(template, copy, reference, rows, via_copy)]
        if template.path.read_bytes() != template.content:
            divergences.append((0, Divergence("NIETKNIETY_WZORZEC", "plik Wzorca na dysku się zmienił")))
        new = []
        for index, divergence in divergences:
            if divergence.known is None:
                new.append((index, divergence))
            elif divergence.known not in self.known or _size(case) < _size(self.known[divergence.known][0]):
                self.known[divergence.known] = (case, index, divergence)
        if new:
            raise Violation(case, new)


def _size(case: Case) -> int:
    return sum(len(rows) for rows in case.workers)


# --- report -----------------------------------------------------------------------------------------


def _value_text(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 60 else f"{text[:40]}… ({len(text)} znaków)"


def story(case: Case, divergences: Sequence[tuple[int, Divergence]]) -> list[str]:
    template = case.template
    lines = [
        f"  Wzorzec {template.name} ({template.description}); kawałki kompresji kopii od wierszy "
        f"{', '.join(map(str, template.chunk_rows))}.",
        "  1. Przebieg rozliczeń wczytuje Wzorzec raz (WorkerSettlementTemplate.check).",
    ]
    for index, rows in enumerate(case.workers, start=1):
        if not rows:
            lines.append(f"  {index + 1}. Rozliczenie pracownika {index}: bez Wierszy danych.")
            continue
        last = FIRST_DATA_ROW + len(rows) - 1
        values = [
            f"{get_column_letter(column)}{FIRST_DATA_ROW + offset}={_value_text(value)}"
            for offset, row in enumerate(rows)
            for column, value in enumerate(row, start=1)
            if value is not None
        ]
        widths = sorted({len(row) for row in rows})
        shown = ", ".join(values[:8]) + (f" i {len(values) - 8} innych" if len(values) > 8 else "")
        lines.append(
            f"  {index + 1}. Rozliczenie pracownika {index}: {len(rows)} Wierszy danych (wiersze {FIRST_DATA_ROW}–{last}, "
            f"{'/'.join(map(str, widths))} wartości w wierszu); niepuste: {shown or 'brak'}."
        )
    for index, divergence in divergences:
        where = f"Rozliczenie pracownika {index}" if index else "Wzorzec"
        lines.append(f"  → {divergence.rule} ({where}): {divergence.detail}")
    return lines


@dataclass(frozen=True)
class Outcome:
    exit_code: int
    lines: list[str]


def run_check(
    examples: int = DEFAULT_EXAMPLES,
    random_seed: int | None = None,
    shrink: bool = True,
    real_template: Path | None = None,
    strict: bool = False,
) -> Outcome:
    started = clock.perf_counter()
    lines: list[str] = []
    if hasattr(hypothesis_engine, "MAX_SHRINKING_SECONDS"):
        hypothesis_engine.MAX_SHRINKING_SECONDS = SHRINK_SECONDS
    with tempfile.TemporaryDirectory(prefix="kopia-wzorca-wzorce-") as scratch:
        templates = build_templates(Path(scratch), real_template)
        run = Run(Routes(), {template.name: Statistics() for template in templates})
        phases = [Phase.explicit, Phase.generate] + ([Phase.shrink] if shrink else [])
        failures: list[Violation] = []
        errors: list[str] = []
        for template in templates:
            # Each Wzorzec gets its own Hypothesis run with the full budget of examples.
            explicit = [Case(template, (_value_rows(),)), _longest_example(template)]
            known_example = _known_finding_example(template)
            if known_example is not None:
                explicit.append(known_example)
            test = _property(run, template, explicit, examples, random_seed, phases)
            try:
                test()
            except Violation as violation:
                failures.append(violation)
            except BaseExceptionGroup as group:
                leaves = list(_leaves(group))
                failures += [error for error in leaves if isinstance(error, Violation)]
                errors += [_checker_error(error) for error in leaves if not isinstance(error, Violation)]
            except Exception as error:  # noqa: BLE001 - a bug in the checker itself ends as LUKA SPRAWDZENIA, not a traceback
                errors.append(_checker_error(error))
        for template in templates:
            statistics = run.statistics[template.name]
            routes = ", ".join(f"{route} {count}" for route, count in sorted(statistics.settlements.items()))
            refusals = f" (odmowy: {dict(statistics.refusals)})" if statistics.refusals else ""
            reached = len(statistics.chunk_rows_reached)
            lines.append(
                f"Wzorzec {template.name}: {statistics.examples} przykładów, Rozliczenia pracowników: {routes}{refusals}; "
                f"do {statistics.max_rows} Wierszy danych; granice kawałków przekroczone: {reached}/{len(template.chunk_rows) - 1}"
            )
    gaps = []
    for template in templates:
        statistics = run.statistics[template.name]
        if failures or not statistics.examples:
            continue
        if statistics.settlements["kopia"] < statistics.settlements["droga openpyxl"]:
            gaps.append(f"Wzorzec {template.name}: kopia użyta rzadziej niż droga openpyxl, sprawdzenie byłoby puste")
        if len(statistics.chunk_rows_reached) < len(template.chunk_rows) - 1:
            gaps.append(f"Wzorzec {template.name}: nie każda granica kawałka kompresji została przekroczona")
    for key, (case, index, divergence) in sorted(run.known.items()):
        lines.append(f"ZNANE USTALENIE {key}: {KNOWN_FINDINGS.get(key, '(brak opisu w KNOWN_FINDINGS)')}")
        lines += story(case, [(index, divergence)])
    for failure in failures:
        lines.append("NOWE NARUSZENIE:")
        lines += story(failure.case, failure.divergences)
    gaps += errors
    lines += [f"LUKA SPRAWDZENIA: {gap}" for gap in gaps]
    lines.append(f"Czas: {clock.perf_counter() - started:.0f} s, {examples} przykładów na Wzorzec.")
    known = len(run.known)
    if errors:
        return Outcome(2, [*lines, f"KOPIA WZORCA: LUKA SPRAWDZENIA ({len(gaps)})"])
    if failures or (strict and known):
        count = len(failures) + (known if strict else 0)
        return Outcome(1, [*lines, f"KOPIA WZORCA: NOWE NARUSZENIE ({count})"])
    if gaps:
        return Outcome(2, [*lines, f"KOPIA WZORCA: LUKA SPRAWDZENIA ({len(gaps)})"])
    return Outcome(0, [*lines, f"KOPIA WZORCA OK, ZNANE USTALENIA: {known}" if known else "KOPIA WZORCA OK"])


def _property(
    run: Run, template: Template, explicit: Sequence[Case], examples: int, random_seed: int | None, phases: list[Phase]
) -> Callable[[], None]:
    @settings(
        max_examples=examples,
        deadline=None,
        database=None,
        derandomize=random_seed is None,
        phases=phases,
        print_blob=False,
        suppress_health_check=list(HealthCheck),
    )
    @given(cases(template))
    def property_holds(case: Case) -> None:
        run.check(case)

    test = property_holds
    for case in explicit:
        test = example(case)(test)
    return seed(random_seed)(test) if random_seed is not None else test


def _checker_error(error: BaseException) -> str:
    notes = " | ".join(getattr(error, "__notes__", []))
    return f"błąd samego sprawdzenia {type(error).__name__}: {error}" + (f" ({notes})" if notes else "")


def _leaves(group: BaseExceptionGroup[BaseException] | None) -> Iterator[BaseException]:
    for error in group.exceptions if group is not None else ():
        if isinstance(error, BaseExceptionGroup):
            yield from _leaves(error)
        else:
            yield error


def _longest_example(template: Template) -> Case:
    """One Rozliczenie pracownika with the most Wiersze danych in scope: it crosses every reachable chunk start."""

    row = ("syntetyczne miasto",) + (None,) * 12 + (1,) + (None,) * (DATA_COLUMNS - 14)
    return Case(template, ((row,) * template.max_rows,))


def _known_finding_example(template: Template) -> Case | None:
    """Smallest case of the known finding: up to the first row of the Wzorzec without a cell in A, left empty."""

    last = FIRST_DATA_ROW + template.max_rows - 1
    gaps = [row for row in range(FIRST_DATA_ROW, min(template.last_row, last) + 1) if (row, 1) not in template.cells]
    if not gaps:
        return None
    rows = [(None, None, "x") + (None,) * (DATA_COLUMNS - 3)] * (gaps[0] - FIRST_DATA_ROW + 1)
    return Case(template, (tuple(rows),))


def _value_rows() -> tuple[ExcelRow, ...]:
    """The value-type rows of the owner test, as a fixed first example."""

    values: list[Any] = [None] * DATA_COLUMNS
    for letter, value in {
        "A": '<b>Miasto & "Wieś"</b> \'1\' ]]>',
        "B": " spacje na brzegach ",
        "C": "=N18*2",
        "D": "=",
        "E": "#N/A",
        "G": date(2026, 9, 8),
        "I": 12345678901234567,
        "J": True,
        "K": datetime(2026, 9, 8, 7, 30, 15),
        "O": 1.25,
        "P": Decimal("2.5"),
        "Q": time(13, 45),
        "AT": "zażółć gęślą jaźń\nnowa linia",
    }.items():
        values[column_index_from_string(letter) - 1] = value
    return (tuple(values), ("tylko miasto",) + (None,) * (DATA_COLUMNS - 1))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--examples", type=int, default=DEFAULT_EXAMPLES, help="Przykłady Hypothesis (domyślnie %(default)s).")
    parser.add_argument("--seed", type=int, help="Losowe przykłady z tego ziarna zamiast stałych (głębsze sprawdzenie).")
    parser.add_argument("--no-shrink", action="store_true", help="Bez zmniejszania kontrprzykładu (szybciej, dla mutacji).")
    parser.add_argument("--wzorzec", type=Path, help="Dodatkowo prawdziwy Wzorzec rozliczenia pracownika (tylko odczyt).")
    parser.add_argument("--strict", action="store_true", help="Znane ustalenia też są naruszeniem.")
    args = parser.parse_args(argv)
    # openpyxl warns about generated numbers too large for a date in a date-formatted column; both paths
    # write them the same, and the gate compares what openpyxl reads.
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
    module = Path(workbook_files.__file__).resolve()
    if not module.is_relative_to(SOURCE_ROOT.resolve()):
        print(f"KOPIA WZORCA: LUKA SPRAWDZENIA (1): rozliczenia importuje się z {module}, nie z {SOURCE_ROOT}")
        return 2
    outcome = run_check(args.examples, args.seed, not args.no_shrink, args.wzorzec, args.strict)
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
