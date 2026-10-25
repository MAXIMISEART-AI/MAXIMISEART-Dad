"""Drive features/uzupelnienie.md."""

from __future__ import annotations

import json
from pathlib import Path
import re
import urllib.request

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import Locator, Page, expect

from create_centrum_fixture import PRICE_LIST
from drive import kontrola_ilosci
from drive.common import LAST_COMPLETE, ROW_MARKER, Run, last_opened_is, period_files, period_row
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
PINNED = ("Nr", "WYKONAWCA", "URZĄDZENIA", "CZYNNOŚCI", "CZYNNOŚCI ZREALIZOWANE")
ROW_TEXTS = ("worker", "devices", "activities", "completed")
ROW_LABELS = {"to_fill": "do uzupełnienia", "done": "zrobiony"}
# Dad's 15,6" 1920×1080 touch screen scaled 150% and 125%, in CSS pixels; the narrower must fit 10 columns N:AP.
DAD_WIDTHS = (1280, 1536)
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


def _check_screen(run: Run, page: Page | Locator, answer: dict[str, object], where: str) -> None:
    """The summary in ``page`` shows every kind's counter and row numbers and every column counter of the answer."""

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


# Every text the result card's summary shows from now on, so a short-lived old copy cannot slip between two checks.
WATCH_RESULT_SUMMARY = """() => {
  window.__resultSummaries = []
  const seen = () => {
    const summary = document.querySelector('[aria-label="Uzupełnienie pliku zbiorczego"]')
    if (summary !== null) window.__resultSummaries.push(summary.textContent)
  }
  window.__resultSummaryObserver = new MutationObserver(seen)
  window.__resultSummaryObserver.observe(document.body, { subtree: true, childList: true, characterData: true })
}"""
SHOWN_RESULT_SUMMARIES = "() => { window.__resultSummaryObserver.disconnect(); return window.__resultSummaries }"


def drive_result_card(run: Run, page: Page) -> None:
    """Entry from Przygotowanie: the written Plik zbiorczy's result card shows the summary and leads to it.

    Then the card after a restart of Centrum, from Logi: the last Uruchomienie is this written Przygotowanie only here.
    """

    run.step(FEATURE, "uzupelnienie-wynik")
    card = page.get_by_role("region", name="Podgląd na żywo")
    filling = card.get_by_role("region", name="Uzupełnienie pliku zbiorczego", exact=True)
    expect(filling.get_by_role("heading", name="Do uzupełnienia w Excelu")).to_be_visible()
    answer = _ready(run, "uzupelnienie-wynik")
    run.check(
        _rows(answer) == {kind: [(row, False) for row in rows] for kind, rows in EXPECTED_ROWS.items()},
        "right after Przygotowanie the server lists rows 18 and 20 without rule and row 19 from the description",
    )
    _check_screen(run, filling, answer, "on the Przygotowanie result card")
    run.capture(page, "230-uzupelnienie-wynik")
    filling.get_by_role("button", name="Uzupełnij", exact=True).click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}")
    _check_screen(run, page, answer, "on the summary opened from the result card")

    run.step(FEATURE, "uzupelnienie-wynik-bez-starej-kopii")
    collective_file = period_files(run)[1]
    original = collective_file.read_bytes()
    try:
        _write_dad_value(collective_file, EXPECTED_ROWS["without_rule"][0])
        page.evaluate(WATCH_RESULT_SUMMARY)
        page.go_back()
        expect(filling).to_contain_text("1 z 2")
        changed = _ready(run, "uzupelnienie-wynik-po-wpisie")
        _check_screen(run, filling, changed, "on the result card after Dad's value")
        shown = page.evaluate(SHOWN_RESULT_SUMMARIES)
        assert isinstance(shown, list)
        run.check(
            not any("0 z 2" in text for text in shown),
            "back on the result card the summary waits for its read instead of the summary page's older copy",
        )
    finally:
        collective_file.write_bytes(original)
    run.check(True, "Uzupełnij on the result card opens the same summary, and Wstecz returns to the result")

    run.step(FEATURE, "uzupelnienie-wynik-po-starcie")
    kontrola_ilosci._close(run, page)
    kontrola_ilosci._start(run, "uzupelnienie-start-po-zamknieciu")
    page.goto(run.url + "#/uruchomienia")
    page.reload()
    restored = page.get_by_role("region", name="Ostatnie Uruchomienie")
    expect(restored.get_by_label("Wynik")).to_contain_text("Plik zbiorczy przygotowany · wymaga sprawdzenia")
    summary = restored.get_by_role("region", name="Uzupełnienie pliku zbiorczego", exact=True)
    expect(summary.get_by_role("heading", name="Do uzupełnienia w Excelu")).to_be_visible()
    _check_screen(run, summary, _ready(run, "uzupelnienie-wynik-po-starcie"), "on the card from Logi after a restart")
    run.capture(page, "232-uzupelnienie-wynik-po-starcie")


def _drive_entries(run: Run, page: Page) -> None:
    """Entries from Okresy: the Tablica okresów row and Droga okresu of the card Następny krok."""

    run.step(FEATURE, "uzupelnienie-tablica")
    page.goto(run.url)
    row = period_row(page, LAST_COMPLETE)
    expect(row).to_contain_text("Plik zbiorczy przygotowany")
    fill = row.get_by_role("button", name=f"Uzupełnij, okres {LAST_COMPLETE}", exact=True)
    others = page.get_by_role("table", name="Tablica okresów").get_by_role("button", name="Uzupełnij, okres", exact=False)
    board = run.api("/api/periods", "uzupelnienie-tablica")
    periods = board["periods"]
    assert isinstance(periods, list)
    prepared = [period["token"] for period in periods if period["status"] == "collective_file_prepared"]
    expect(others).to_have_count(len(prepared))
    for token in prepared:
        expect(period_row(page, token).get_by_role("button", name=f"Uzupełnij, okres {token}", exact=True)).to_be_visible()
    run.check(
        LAST_COMPLETE in prepared and len(prepared) < len(periods),
        f"exactly the rows with Status okresu Plik zbiorczy przygotowany ({', '.join(prepared)}) offer Uzupełnij",
    )
    run.capture(page, "231-uzupelnienie-tablica")
    fill.click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/{SUMMARY}")
    expect(page.get_by_role("heading", level=1)).to_have_text("Uzupełnienie pliku zbiorczego")
    _check_screen(run, page, _ready(run, "uzupelnienie-z-tablicy"), "on the summary opened from Tablica okresów")

    run.step(FEATURE, "uzupelnienie-droga")
    page.go_back()
    path = page.get_by_role("region", name="Następny krok").get_by_role("list", name="Droga okresu")
    current = path.locator('[aria-current="step"]')
    expect(current).to_have_count(1)
    expect(current).to_contain_text("Uzupełnienie w Excelu")
    expect(path.get_by_role("img", name="zrobione")).to_have_count(1)
    run.check(True, "Droga okresu shows Uzupełnienie w Excelu as the current step after Plik zbiorczy")


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
    original = page.viewport_size
    for width in DAD_WIDTHS:
        page.set_viewport_size({"width": width, "height": 800})
        visible = table.evaluate(
            """table => {
                const right = table.parentElement.getBoundingClientRect().right
                return [...table.querySelectorAll("thead th")].slice(5)
                    .filter((th) => th.getBoundingClientRect().right <= right + 0.5).length
            }"""
        )
        run.check(
            width > DAD_WIDTHS[0] or visible >= 10,
            f"{title}: at {width} px with the menu open {visible} columns N:AP fit next to the pinned texts",
        )
        _capture(run, page, f"{shot}-{width}px", answer)
    if original is not None:
        page.set_viewport_size(original)
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
    # Alone the period has no Plik zbiorczy; in `all`, tablica-okresow has left one there.
    on_disk = (Path(run.fixture["periods_directory"]) / EMPTY_PERIOD / f"Rozliczenie {EMPTY_PERIOD} - zbiorcze.xlsx").is_file()
    expect(page.get_by_role("button", name="Otwórz Plik zbiorczy", exact=True)).to_have_count(1 if on_disk else 0)
    run.check(
        answer["collective_file_exists"] is on_disk,
        f"Otwórz Plik zbiorczy is there only when the Plik zbiorczy is in the Folder okresu ({on_disk=})",
    )
    page.goto(f"{run.url.rstrip('/')}/#/uzupelnienie/{EMPTY_PERIOD}/without_rule")
    expect(page.get_by_label("Komunikat", exact=True)).to_contain_text(str(message["what"]))
    expect(page.get_by_role("button", name="Otwórz Plik zbiorczy", exact=True)).to_have_count(1 if on_disk else 0)
    run.check(True, "the kind page of the same period follows the same rule")
    page.go_back()
    log = (run.root / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8").splitlines()
    run.check(
        any(" uzupelnienie-odczyt-nieudany " in line and f"okres={EMPTY_PERIOD}" in line for line in log),
        "the failed read is in the Centrum log with the period",
    )
    run.capture(page, "224-uzupelnienie-bez-pliku")


def _drive(run: Run, page: Page, collective_file: Path, lock: Path) -> None:
    _drive_entries(run, page)
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
    run.capture(page, "220-uzupelnienie-karta")

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
    run.capture(page, "221-uzupelnienie-podsumowanie")

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
    run.capture(page, "222-uzupelnienie-po-wpisie")
    if switched:
        page.locator("header").get_by_role("button", name="Włącz motyw ciemny", exact=True).click()

    run.step(FEATURE, "uzupelnienie-tabela-bez-reguly")
    without_rule = _drive_kind(run, page, "without_rule", "225-uzupelnienie-bez-reguly")
    rows = without_rule["rows"]
    assert isinstance(rows, list)
    dad_cells = {row["row"]: [cell for cell in row["cells"] if cell["source"] == "tata"] for row in rows}
    run.check(
        [row["state"] for row in rows] == ["done", "to_fill"] and dad_cells == {18: [{"source": "tata", "value": 1}], 20: []},
        f"Dad's value in {DAD_COLUMN}18 comes back green with his value and makes row 18 done; row 20 stays to fill",
    )

    run.step(FEATURE, "uzupelnienie-tabela-z-opisu")
    _drive_kind(run, page, "from_description", "226-uzupelnienie-z-opisu")

    run.step(FEATURE, "uzupelnienie-blokada-excela")
    lock.write_bytes(b"\x00" * 165)
    page.reload()
    held = _ready(run, "uzupelnienie-blokada-excela")
    run.check(
        held == after,
        "with Excel's lock file next to the Plik zbiorczy the server reads its last saved version unchanged",
    )
    _check_screen(run, page, held, "with Excel's lock file")
    run.capture(page, "223-uzupelnienie-blokada-excela")

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

    run.step(FEATURE, "uzupelnienie-gotowe")
    lock.unlink()
    run.check(not lock.exists(), "harness: Dad closed Excel, so no lock file keeps Uruchom disabled")
    expected = _without_quantity(_ready(run, "uzupelnienie-gotowe-podsumowanie"))
    answer = _go_to_settlement(run, page, LAST_COMPLETE, "uzupelnienie-gotowe")
    run.check(
        answer == {"state": "read", "rows": expected, "sentence": "2 wiersze bez ilości: 19, 20"} and expected == [19, 20],
        "the period's rows without quantity are 19 and 20, the summary's rows not done",
    )
    run.capture(page, "215-uzupelnienie-gotowe")

    run.step(FEATURE, "uzupelnienie-gotowe-potwierdzenie")
    page.get_by_role("button", name="Uruchom", exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
    expect(confirm).to_contain_text("„Uruchom” potwierdza Gotowość Pliku zbiorczego")
    expect(confirm).to_contain_text("2 wiersze bez ilości: 19, 20")
    expect(confirm.get_by_role("button", name="Uruchom", exact=True)).to_be_enabled()
    run.check(True, "the confirm dialog lists the rows without quantity, and Dad may still start")
    run.capture(page, "216-uzupelnienie-gotowe-potwierdzenie")
    confirm.get_by_role("button", name="Anuluj", exact=True).click()
    expect(confirm).to_have_count(0)

    run.step(FEATURE, "uzupelnienie-gotowe-po-podgladzie")
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    live = page.get_by_role("region", name="Podgląd na żywo")
    expect(live).to_contain_text("Podgląd gotowy · nic nie zapisano")
    live.get_by_role("button", name="Uruchom", exact=True).click()
    confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
    expect(confirm).to_contain_text("2 wiersze bez ilości: 19, 20")
    expect(confirm.get_by_role("button", name="Uruchom", exact=True)).to_be_enabled()
    run.check(True, "after the preview, the result card's Uruchom dialog lists the same rows, Dad's usual path")
    run.capture(page, "218-uzupelnienie-gotowe-po-podgladzie")
    confirm.get_by_role("button", name="Anuluj", exact=True).click()
    expect(confirm).to_have_count(0)

    run.step(FEATURE, "uzupelnienie-gotowe-bez-odczytu")
    other = run.fixture["settlement"]["needs_check"]
    assert isinstance(other, str)
    other_file = Path(str(run.fixture["periods_directory"])) / other / f"Rozliczenie {other} - zbiorcze.xlsx"
    saved = other_file.read_bytes()
    try:
        other_file.write_bytes(b"to nie jest skoroszyt")
        run.check(True, f"harness: the Plik zbiorczy of {other} is damaged for this step and restored after it")
        page.goto(f"{run.url.rstrip('/')}/#/uzupelnienie/{other}")
        expect(page.get_by_role("main").get_by_text(other, exact=True)).to_be_visible()
        answer = _go_to_settlement(run, page, other, "uzupelnienie-gotowe-bez-odczytu")
        run.check(
            answer == {"state": "unread"},
            f"Gotowe on the summary of {other} selects it, not the preselected {LAST_COMPLETE}, and its rows "
            "without quantity answer although its Plik zbiorczy cannot be read",
        )
        page.get_by_role("button", name="Uruchom", exact=True).click()
        confirm = page.get_by_role("alertdialog", name="Uruchomić z zapisem?")
        expect(confirm).to_contain_text("Nie udało się sprawdzić wierszy bez ilości")
        expect(confirm.get_by_role("button", name="Uruchom", exact=True)).to_be_enabled()
        run.check(True, "the dialog says the rows could not be checked instead of staying silent, and Dad may start")
        run.capture(page, "217-uzupelnienie-gotowe-bez-odczytu")
        confirm.get_by_role("button", name="Anuluj", exact=True).click()
    finally:
        other_file.write_bytes(saved)
    # The draft of the Przebieg form lives in the page; the next feature must start without it.
    page.goto(run.url)
    page.reload()


def _without_quantity(answer: dict[str, object]) -> list[int]:
    return sorted(row for rows in _rows(answer).values() for row, done in rows if not done)


def _go_to_settlement(run: Run, page: Page, period: str, name: str) -> dict[str, object]:
    """Clicks Gotowe on the summary: Przebieg rozliczeń with the period chosen; returns the period's rows without quantity."""

    page.get_by_role("button", name="Gotowe, rozlicz pracowników", exact=True).click()
    expect(page).to_have_url(f"{run.url.rstrip('/')}/#/uruchomienia")
    expect(page.get_by_text("Nowe Uruchomienie procesu", exact=True)).to_be_visible()
    expect(page.get_by_role("radio", name="Przebieg rozliczeń")).to_be_checked()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)
    processes = run.api("/api/runs/setup", name)["processes"]
    assert isinstance(processes, list)
    [setup] = [process for process in processes if process["process"] == "settlement"]
    run.check(
        processes[0]["process"] != "settlement"
        and setup["preselected_period"] == LAST_COMPLETE
        and period in [choice["token"] for choice in setup["periods"]],
        f"Gotowe chose Przebieg rozliczeń and {period}; without it the form shows the first process",
    )
    return run.api(f"/api/periods/{period}/without-quantity", f"{name}-wiersze")
