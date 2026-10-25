"""Drive features/uzupelnienie.md."""

from __future__ import annotations

import json
from pathlib import Path
import re
import urllib.request

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import Page, expect

from create_centrum_fixture import PRICE_LIST
from drive.common import LAST_COMPLETE, ROW_MARKER, Run, last_opened_is, period_files
from drive.przygotowanie_pliku_zbiorczego import drive_preparation

FEATURE = "uzupelnienie"
SUMMARY = f"#/uzupelnienie/{LAST_COMPLETE}"
API = f"/api/periods/{LAST_COMPLETE}/quantities-to-fill"
KIND_TITLES = {"without_rule": "Wiersze bez reguły", "from_description": "Wiersze z opisu"}
# The fixture's Plik zbiorczy after Przygotowanie: rows 18 and 20 carry a device the Reguły ilości do not know,
# row 19 is prewencja (create_centrum_fixture.py, DEVICES).
EXPECTED_ROWS = {"without_rule": [18, 20], "from_description": [19]}
# Dad's value goes into a column from the technician's description: it is outside V, T and N, so it also makes
# its row without rule done, and it moves that column's counter.
DAD_COLUMN = "Y"
# The pinned column headers of a kind's table, the row texts the browser gets, and each row state's words.
PINNED = ("Wiersz", "WYKONAWCA", "URZĄDZENIA", "CZYNNOŚCI", "CZYNNOŚCI ZREALIZOWANE")
ROW_TEXTS = ("worker", "devices", "activities", "completed")
ROW_LABELS = {"to_fill": "do uzupełnienia", "done": "zrobiony"}
# A period whose Folder okresu holds no Plik zbiorczy.
EMPTY_PERIOD = "15_21_09_2026"


def _in_rows(rows: int) -> str:
    return "nic nie wpisano" if rows == 0 else f"wpisane w {rows} {'wierszu' if rows == 1 else 'wierszach'}"


def _ready(run: Run, name: str) -> dict[str, object]:
    answer = run.api(API, name)
    run.check(answer["state"] == "ready", f"{name}: the server read the Plik zbiorczy")
    return answer


def _rows(answer: dict[str, object]) -> dict[str, list[tuple[int, bool]]]:
    """Each kind's rows as (row number, done)."""

    kinds = answer["kinds"]
    assert isinstance(kinds, list)
    return {kind["kind"]: [(row["row"], row["done"]) for row in kind["rows"]] for kind in kinds}


def _columns(answer: dict[str, object]) -> dict[str, int]:
    columns = answer["description_columns"]
    assert isinstance(columns, list)
    return {column["column"]: column["rows"] for column in columns}


def _check_screen(run: Run, page: Page, answer: dict[str, object], where: str) -> None:
    """The summary shows every kind's counter and row numbers and every column counter of the server's answer."""

    kinds = answer["kinds"]
    assert isinstance(kinds, list)
    for kind in kinds:
        rows = [(row["row"], row["done"]) for row in kind["rows"]]
        section = page.get_by_role("region", name=KIND_TITLES[kind["kind"]], exact=True)
        if rows:
            expect(section).to_contain_text(f"{sum(done for _, done in rows)} z {len(rows)}")
        else:
            expect(section).to_contain_text("Nie ma takich wierszy.")
        expect(section.get_by_role("img", name="Zrobione" if kind["done"] else "Do uzupełnienia")).to_be_visible()
        expect(section.get_by_role("listitem")).to_have_text([f"{row}{' zrobiony' if done else ''}" for row, done in rows])
    columns = _columns(answer)
    reminder = page.get_by_role("region", name="Kolumny z opisu technika", exact=True)
    expect(reminder.locator("dt")).to_have_text(list(columns))
    expect(reminder.locator("dd")).to_have_text([_in_rows(rows) for rows in columns.values()])
    run.check(True, f"{where}: counters, row numbers with their done state, and column counters match the server")


def _shown(cell: dict[str, object]) -> str:
    """A quantity cell's text as the table renders it, screen-reader words included."""

    value = cell["value"]
    if value == 0:
        return ""
    if value == "nieliczbowa":
        return "? nieliczbowa"
    return f"{value} narzędzie" if cell["source"] == "tool" else str(value)


def _without_texts(answer: dict[str, object]) -> dict[str, object]:
    """The answer with the four row texts replaced: what is left must not carry any workbook content."""

    rows = answer["rows"]
    assert isinstance(rows, list)
    hidden = dict.fromkeys(ROW_TEXTS, "<tekst wiersza>")
    return {**answer, "rows": [{**row, **hidden} for row in rows]}


def _kind_answer(run: Run, kind: str) -> dict[str, object]:
    """The kind's table from the server; the evidence keeps it without the row texts, which are workbook content."""

    with urllib.request.urlopen(f"{run.url.rstrip('/')}{API}/{kind}", timeout=10) as response:
        answer = json.load(response)
    assert isinstance(answer, dict)
    (run.evidence / "api" / f"uzupelnienie-tabela-{kind}.json").write_text(
        json.dumps(_without_texts(answer), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return answer


def _capture(run: Run, page: Page, name: str, answer: dict[str, object]) -> None:
    """Screenshot of a kind page; its ARIA snapshot keeps the row texts out, like the saved answer."""

    run.capture(page, name)
    rows = answer["rows"]
    assert isinstance(rows, list)
    snapshot = run.evidence / "aria" / f"{name}.txt"
    text = snapshot.read_text(encoding="utf-8")
    for row in rows:
        for field in ROW_TEXTS:
            if row[field]:
                text = text.replace(row[field], "<tekst wiersza>")
    snapshot.write_text(text, encoding="utf-8")


def _drive_kind(run: Run, page: Page, kind: str, shot: str) -> dict[str, object]:
    """From the summary, open the kind's table and check it against the server; returns the server's answer."""

    title = KIND_TITLES[kind]
    log_path = run.root / "logs" / "centrum-rozliczen.log"
    since = len(log_path.read_text(encoding="utf-8").splitlines())
    page.get_by_role("region", name=title, exact=True).get_by_role("link").click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}/{kind}")
    table = page.get_by_role("table", name="Wiersze Pliku zbiorczego", exact=True)
    expect(table).to_be_visible()
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    expect(page.get_by_role("main").get_by_role("heading", level=2)).to_have_text([title])
    answer = _kind_answer(run, kind)
    rows = answer["rows"]
    columns = answer["columns"]
    assert isinstance(rows, list) and isinstance(columns, list)
    run.check(
        answer["state"] == "ready" and [row["row"] for row in rows] == EXPECTED_ROWS[kind],
        f"{title}: the server lists only this kind's rows, ascending",
    )
    run.check(
        ROW_MARKER not in json.dumps(_without_texts(answer), ensure_ascii=False) and all(ROW_MARKER in row["completed"] for row in rows),
        f"{title}: the answer carries the row texts and no address, order number or UMOWA",
    )
    run.check(
        [column["name"] for column in columns] == list(PRICE_LIST),
        f"{title}: every column N:AP carries its price-list name from row 17 of the Plik zbiorczy",
    )

    expect(table.get_by_role("columnheader")).to_have_count(len(PINNED) + len(columns))
    expect(table.get_by_role("columnheader")).to_have_text(
        [*PINNED, *(re.compile(f"^{column['column']}{re.escape(column['name'])}$") for column in columns)]
    )
    expect(table.get_by_role("rowheader")).to_have_text([f"{row['row']} {ROW_LABELS[row['state']]}" for row in rows])
    for row in rows:
        line = table.locator(f"tr[data-state='{row['state']}']", has=page.get_by_role("rowheader", name=str(row["row"])))
        expect(line.locator("td[data-source]")).to_have_text([_shown(cell) for cell in row["cells"]])
        expect(line.locator("td[data-source='tata']")).to_have_count(
            sum(cell["source"] == "tata" for cell in row["cells"])
        )
    run.check(True, f"{title}: row numbers, row states and every N:AP cell on screen equal the server's answer")

    [first] = columns[:1]
    table.get_by_role("button", name=f"{first['column']}: {first['name']}", exact=True).click()
    expect(page.locator("[data-slot=popover-content]")).to_contain_text(first["name"])
    page.keyboard.press("Escape")
    expect(page.locator("[data-slot=popover-content]")).to_have_count(0)
    completed = rows[0]["completed"]
    table.get_by_role("button", name=f"CZYNNOŚCI ZREALIZOWANE: {completed}", exact=True).click()
    expect(page.locator("[data-slot=popover-content]")).to_contain_text(completed)
    run.check(True, f"{title}: a tap on a column header or on CZYNNOŚCI ZREALIZOWANE shows the full text")
    run.wait_for(
        lambda: any(
            " pomiar " in line and "strona=uzupelnienie" in line and "getKindTable:" in line
            for line in log_path.read_text(encoding="utf-8").splitlines()[since:]
        ),
        f"{title}: the view is measured as page uzupelnienie with its getKindTable request",
    )
    _capture(run, page, f"{shot}-otwarty-opis", answer)
    page.keyboard.press("Escape")
    switched = _light_theme(page)
    _capture(run, page, f"{shot}-jasny", answer)
    if switched:
        page.locator("header").get_by_role("button", name="Włącz motyw ciemny", exact=True).click()

    number = table.get_by_role("rowheader").first
    before = number.bounding_box()
    table.locator("xpath=..").evaluate("box => { box.scrollLeft = box.scrollWidth }")
    expect(table.get_by_role("columnheader", name=re.compile("^AP")).first).to_be_in_viewport()
    after = number.bounding_box()
    run.check(
        before is not None and after is not None and before["x"] == after["x"],
        f"{title}: the row number stays in place while the quantity columns scroll sideways",
    )
    # Column Y (Dad's value in row 18) right after the pinned columns, as Dad would scroll to it.
    table.evaluate(
        """table => {
            const [n, y] = ["N", "Y"].map((letter) =>
                [...table.querySelectorAll("thead th")].find((th) => th.textContent.startsWith(letter))
            )
            table.parentElement.scrollLeft = y.offsetLeft - n.offsetLeft
        }"""
    )
    _capture(run, page, f"{shot}-przewiniete", answer)

    page.get_by_role("main").get_by_role("link", name="Podsumowanie", exact=True).click()
    expect(page.get_by_role("region", name="Kolumny z opisu technika", exact=True)).to_be_visible()
    return answer


def _write_dad_value(collective_file: Path, row: int) -> None:
    """Dad types one quantity in Excel and saves (harness: openpyxl edits the run's Plik zbiorczy, no lock file)."""

    workbook = load_workbook(collective_file)
    try:
        sheet = workbook.active
        assert isinstance(sheet, Worksheet)
        sheet.cell(row, column_index_from_string(DAD_COLUMN)).value = 1
        workbook.save(collective_file)
    finally:
        workbook.close()


def _light_theme(page: Page) -> bool:
    """Switches to the light theme for the screenshot; True when it was dark and must be switched back."""

    light = page.locator("header").get_by_role("button", name="Włącz motyw jasny", exact=True)
    if light.count() == 0:
        return False
    light.click()
    expect(page.locator("header").get_by_role("button", name="Włącz motyw ciemny", exact=True)).to_be_visible()
    return True


def drive_filling(run: Run, page: Page) -> None:
    _, collective_file = period_files(run)
    if not collective_file.is_file():
        # Dad's path starts with Przygotowanie pliku zbiorczego; alone, this feature drives it first.
        drive_preparation(run, page)
    original = collective_file.read_bytes()
    lock = collective_file.with_name(f"~${collective_file.name}")
    try:
        _drive(run, page, collective_file, lock)
    finally:
        # The harness's value must not reach Przebieg rozliczeń, which continues from this Plik zbiorczy.
        collective_file.write_bytes(original)
        lock.unlink(missing_ok=True)

    run.step(FEATURE, "uzupelnienie-bez-pliku")
    page.goto(f"{run.url.rstrip('/')}/#/uzupelnienie/{EMPTY_PERIOD}")
    answer = run.api(f"/api/periods/{EMPTY_PERIOD}/quantities-to-fill", "uzupelnienie-bez-pliku")
    message = answer["message"]
    assert isinstance(message, dict)
    notice = page.get_by_label("Komunikat", exact=True)
    for part in ("what", "where", "action"):
        expect(notice).to_contain_text(message[part])
    run.check(
        answer["state"] == "problem" and page.get_by_role("alert").filter(has_text="Nie udało się").count() == 0,
        "a period without a Plik zbiorczy shows the server's three-part Komunikat, calm and not as a failure",
    )
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8").splitlines()
    run.check(
        any(" uzupelnienie-odczyt-nieudany " in line and f"okres={EMPTY_PERIOD}" in line for line in log),
        "the failed read is in the Centrum log with the period",
    )
    run.capture(page, "214-uzupelnienie-bez-pliku")


def _drive(run: Run, page: Page, collective_file: Path, lock: Path) -> None:
    run.step(FEATURE, "uzupelnienie-karta")
    page.goto(run.url)
    next_step = page.get_by_role("region", name="Następny krok")
    expect(next_step).to_contain_text(LAST_COMPLETE)
    expect(next_step).to_contain_text("Utwórz rozliczenia pracowników")
    fill = next_step.get_by_role("button", name="Uzupełnij", exact=True)
    expect(fill).to_be_visible()
    expect(next_step.get_by_role("button", name="Podgląd bez zapisu", exact=True)).to_be_visible()
    board = run.api("/api/periods", "uzupelnienie-karta")
    periods = board["periods"]
    assert isinstance(periods, list)
    [last] = [period for period in periods if period["last_complete"]]
    run.check(
        last["token"] == LAST_COMPLETE and last["status"] == "collective_file_prepared",
        "Następny krok offers Uzupełnij for the last complete period with Plik zbiorczy przygotowany, "
        "with Podgląd bez zapisu next to it",
    )
    run.capture(page, "210-uzupelnienie-karta")

    run.step(FEATURE, "uzupelnienie-podsumowanie")
    log_path = run.root / "logs" / "centrum-rozliczen.log"
    since = len(log_path.read_text(encoding="utf-8").splitlines())
    fill.click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}")
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    expect(page.get_by_role("main").get_by_text(LAST_COMPLETE, exact=True)).to_be_visible()
    before = _ready(run, "uzupelnienie-podsumowanie")
    run.check(
        _rows(before) == {kind: [(row, False) for row in rows] for kind, rows in EXPECTED_ROWS.items()},
        "the server lists rows 18 and 20 without rule and row 19 from the description, none done yet",
    )
    _check_screen(run, page, before, "after Uzupełnij")
    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    expect(menu.get_by_role("link", name="Okresy", exact=True)).to_have_attribute("data-active", "")
    run.wait_for(
        lambda: any(
            " pomiar " in line and "strona=uzupelnienie" in line and "getQuantitiesToFill:" in line
            for line in log_path.read_text(encoding="utf-8").splitlines()[since:]
        ),
        "the view is measured as page uzupelnienie with its getQuantitiesToFill request",
    )
    run.capture(page, "211-uzupelnienie-podsumowanie")

    run.step(FEATURE, "uzupelnienie-wpis-taty")
    row = EXPECTED_ROWS["without_rule"][0]
    _write_dad_value(collective_file, row)
    run.check(not lock.exists(), f"harness: one value typed into column {DAD_COLUMN} of row {row}, saved and closed")
    page.reload()
    after = _ready(run, "uzupelnienie-po-wpisie")
    columns_before, columns_after = _columns(before), _columns(after)
    run.check(
        _rows(after) == {**_rows(before), "without_rule": [(18, True), (20, False)]}
        and columns_after == {**columns_before, DAD_COLUMN: columns_before[DAD_COLUMN] + 1},
        f"after a reload row {row} is done and only column {DAD_COLUMN} counts one more row",
    )
    _check_screen(run, page, after, "after Dad's value")
    switched = _light_theme(page)
    run.capture(page, "212-uzupelnienie-po-wpisie")
    if switched:
        page.locator("header").get_by_role("button", name="Włącz motyw ciemny", exact=True).click()

    run.step(FEATURE, "uzupelnienie-tabela-bez-reguly")
    without_rule = _drive_kind(run, page, "without_rule", "215-uzupelnienie-bez-reguly")
    rows = without_rule["rows"]
    assert isinstance(rows, list)
    dad_cells = {row["row"]: [cell for cell in row["cells"] if cell["source"] == "tata"] for row in rows}
    run.check(
        [row["state"] for row in rows] == ["done", "to_fill"] and dad_cells == {18: [{"source": "tata", "value": 1}], 20: []},
        f"Dad's value in {DAD_COLUMN}18 comes back green with his value and makes row 18 done; row 20 stays to fill",
    )

    run.step(FEATURE, "uzupelnienie-tabela-z-opisu")
    _drive_kind(run, page, "from_description", "216-uzupelnienie-z-opisu")

    run.step(FEATURE, "uzupelnienie-blokada-excela")
    lock.write_bytes(b"\x00" * 165)
    page.reload()
    held = _ready(run, "uzupelnienie-blokada-excela")
    run.check(
        held == after,
        "with Excel's lock file next to the Plik zbiorczy the server reads its last saved version unchanged",
    )
    _check_screen(run, page, held, "with Excel's lock file")
    run.capture(page, "213-uzupelnienie-blokada-excela")

    run.step(FEATURE, "uzupelnienie-otworz")
    page.get_by_role("button", name="Otwórz Plik zbiorczy", exact=True).click()
    run.wait_for(last_opened_is(run, collective_file), "Otwórz Plik zbiorczy opened the period's Plik zbiorczy")
    expect(page.get_by_text(collective_file.name, exact=True).last).to_be_visible()

    run.step(FEATURE, "uzupelnienie-powrot")
    page.get_by_role("main").get_by_role("link", name="Okresy", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Okresy")
    page.go_back()
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    run.check(True, "the link Okresy leads back, and Wstecz returns to the summary of the same period")
