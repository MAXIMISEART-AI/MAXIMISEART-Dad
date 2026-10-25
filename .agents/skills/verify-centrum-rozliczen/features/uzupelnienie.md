# Uzupełnienie pliku zbiorczego

After Przygotowanie pliku zbiorczego, Dad types the Ilości do uzupełnienia in
Excel. The card `Następny krok` on Okresy offers `Uzupełnij` for a period with
Plik zbiorczy przygotowany, and it leads to the period's summary at
`#/uzupelnienie/<token>`: a counter „x z y” and the row numbers for `Wiersze bez
reguły` and `Wiersze z opisu` (done rows crossed out, a kind with no rows or
all rows done ticked, never red), how many rows hold a value in each column
from the technician's description, and `Otwórz Plik zbiorczy`. Centrum reads
the saved Plik zbiorczy on every read, also while Excel holds it, and never
changes it. Each kind with rows opens its own page at
`#/uzupelnienie/<token>/<kind>`: a read-only table like Excel with only that
kind's rows, the row number and WYKONAWCA, URZĄDZENIA, CZYNNOŚCI and CZYNNOŚCI
ZREALIZOWANE pinned on the left, all 29 columns N:AP scrolling sideways under
their letter and price-list name, the tool's values grey, a row to fill yellow,
and Dad's value green in a green row. A Plik zbiorczy it cannot read is a calm
three-part Komunikat.

## Sub-features

- `uzupelnienie-karta`: the card `Następny krok` for the last complete period with Status `Plik zbiorczy przygotowany` has `Uzupełnij` as its primary action and `Podgląd bez zapisu` next to it.
- `uzupelnienie-podsumowanie`: `Uzupełnij` opens `#/uzupelnienie/06_12_10_2026` with the period token in the title row; the counters, row numbers and column counters equal `GET /api/periods/<token>/quantities-to-fill`; the sidebar highlights Okresy; the view is measured as page `uzupelnienie`.
- `uzupelnienie-wpis-taty`: one value Dad types in column Y of row 18 (harness, openpyxl) makes, after a reload, row 18 done (`1 z 2`) and column Y count one more row; nothing else changes.
- `uzupelnienie-tabela-bez-reguly`: the region `Wiersze bez reguły` links to `#/uzupelnienie/06_12_10_2026/without_rule`; its table equals `GET /api/periods/<token>/quantities-to-fill/without_rule` row by row and cell by cell, Dad's value in Y18 is a green cell in the done row 18, a tap on a column header or on CZYNNOŚCI ZREALIZOWANE shows the full text, the row number stays put while N:AP scroll sideways, and the answer has no address, order number or UMOWA.
- `uzupelnienie-tabela-z-opisu`: the same for `Wiersze z opisu` (`#/uzupelnienie/06_12_10_2026/from_description`, row 19, no tool values).
- `uzupelnienie-blokada-excela`: Excel's lock file `~$…` next to the Plik zbiorczy changes neither the server's answer nor the screen.
- `uzupelnienie-otworz`: `Otwórz Plik zbiorczy` opens the period's Plik zbiorczy (`opened.jsonl`).
- `uzupelnienie-powrot`: the link `Okresy` leads back and Wstecz returns to the same summary.
- `uzupelnienie-bez-pliku`: a period without a Plik zbiorczy shows the server's three-part Komunikat (label `Komunikat`), not a failure, and the Centrum log has `uzupelnienie-odczyt-nieudany` with the period.

## How to get to it (user POV)

- Okresy → card `Następny krok` → `Uzupełnij` (when the last complete period has Plik zbiorczy przygotowany).
- The address `#/uzupelnienie/<token>` directly, also after a reload or Wstecz.

## Driving it with Playwright for Python

Preconditions:

- The last complete period `06_12_10_2026` has Status `Plik zbiorczy przygotowany`. In `all` this feature runs right after `przygotowanie-pliku-zbiorczego`; alone, it drives that feature first.
- After Przygotowanie the fixture's Plik zbiorczy has rows 18 and 20 without rule (a device the Reguły ilości do not know) and row 19 from the description (`prewencja`; `DEVICES` in `create_centrum_fixture.py`), none done.

- **Card.** On Okresy, region `Następny krok` shows `06_12_10_2026` and `Utwórz rozliczenia pracowników`, button `Uzupełnij` (an `<a>` rendered as a button) and button `Podgląd bez zapisu`. `GET /api/periods` (`api/uzupelnienie-karta.json`) has the last complete period with `status: collective_file_prepared`. Screenshot `220`.
- **Summary.** Click `Uzupełnij`: the URL ends in `#/uzupelnienie/06_12_10_2026`, heading level 1 `Uzupełnienie pliku zbiorczego`, the token in `main`. `GET /api/periods/06_12_10_2026/quantities-to-fill` (`api/uzupelnienie-podsumowanie.json`) is `ready` with rows `[18, 20]` and `[19]`, none done. Regions `Wiersze bez reguły` and `Wiersze z opisu` each show `<done> z <rows>`, the image `Zrobione` or `Do uzupełnienia` after the kind's `done`, and list items with the row numbers in order (a done row reads `18 zrobiony`; a kind without rows says `Nie ma takich wierszy.`). Region `Kolumny z opisu technika` has one `dt` per column (Y, AB, AD, AJ, AK, AL, AM) and its `dd` `nic nie wpisano`, `wpisane w 1 wierszu` or `wpisane w N wierszach`. The sidebar link `Okresy` has `data-active`. A `pomiar` line with `strona=uzupelnienie` and `getQuantitiesToFill:` reaches the Centrum log. Screenshot `221`.
- **Dad's value.** Harness (labelled in `drive.txt`): openpyxl writes `1` into Y18 of the run's Plik zbiorczy, saves and closes it, with no lock file. `page.reload()`: the answer (`api/uzupelnienie-po-wpisie.json`) has row 18 done, row 20 not, column Y one more row, everything else unchanged; the screen shows `1 z 2` and `18 zrobiony`. Screenshot `222` in the light theme (the drive switches the theme for it and back).
- **Kind pages.** Still with Dad's value in Y18, click the link in region `Wiersze bez reguły`: the URL ends in `/without_rule`, heading level 1 `Uzupełnienie pliku zbiorczego` and level 2 `Wiersze bez reguły`. The drive reads `GET /api/periods/06_12_10_2026/quantities-to-fill/without_rule` itself and keeps it as `api/uzupelnienie-tabela-without_rule.json` with the four row texts replaced by `<tekst wiersza>` (they are workbook content). Checks: rows `[18, 20]` ascending; without the row texts the answer holds no `ROW_MARKER` (no address, order number or UMOWA), while every `completed` holds it; the column names equal `PRICE_LIST` (`create_centrum_fixture.py`, N17:AP17 of the Wzorzec pliku zbiorczego); table `Wiersze Pliku zbiorczego` has 5 pinned column headers and one per N:AP (letter and name); row headers read `<row> zrobiony` or `<row> do uzupełnienia`; every `td[data-source]` of a row (`data-state` on its `tr`) reads what the answer's cell shows (`<value> narzędzie` for the tool, Dad's value, empty for 0, `? nieliczbowa`) and the `tata` cells count as many as in the answer; row 18 is `done` with exactly one Dad's cell Y = 1, row 20 is `to_fill`. A click on the first column header and on row 18's CZYNNOŚCI ZREALIZOWANE opens a popover (`[data-slot=popover-content]`) with the full text; a `pomiar` line with `getKindTable:` reaches the log. Screenshot `225-uzupelnienie-bez-reguly-otwarty-opis` with the popover open. At 1280 px wide (Dad's 1920×1080 screen at 150%) with the menu open at least 10 columns N:AP fit next to the pinned texts; screenshots `225-…-1280px` and `225-…-1536px`, then the original viewport and `225-…-jasny` in the light theme. Scrolling the table's box to the far right brings `AP` into view while the first row header keeps its `x`: screenshot `225-uzupelnienie-bez-reguly-przewiniete`. Link `Podsumowanie` in `main` leads back to the summary. Then the same for `Wiersze z opisu` (row 19), screenshots `226-uzupelnienie-z-opisu-*`.
- **Excel's lock.** Write `~$Rozliczenie 06_12_10_2026 - zbiorcze.xlsx` next to the file and reload: the answer (`api/uzupelnienie-blokada-excela.json`) equals the previous one, and so does the screen. Screenshot `223`.
- **Open.** Click `Otwórz Plik zbiorczy`: the last line of `opened.jsonl` is the period's Plik zbiorczy, and the toast names it.
- **Back.** Click link `Okresy` in `main`: heading `Okresy`. `page.go_back()`: heading `Uzupełnienie pliku zbiorczego` again.
- **Restore.** In `finally` the drive writes back the Plik zbiorczy's original bytes and removes the lock file.
- **No Plik zbiorczy.** Open `#/uzupelnienie/15_21_09_2026` (empty Folder okresu): label `Komunikat` shows the answer's `what`, `where` and `action` (`api/uzupelnienie-bez-pliku.json`, `state: problem`), no alert `Nie udało się …`, and the Centrum log has `uzupelnienie-odczyt-nieudany … okres=15_21_09_2026`. Screenshot `224`.
- **Proof.** Screenshots `220`–`226`, `api/uzupelnienie-*.json`, checks in `drive.txt`.

## Gotchas

- Restore the Plik zbiorczy: `przebieg-rozliczen` continues from it, and a value left in Y18 would reach a Rozliczenie pracownika and the Kontrola ilości.
- `Uzupełnij` has role `button`, not `link`: it is a Base UI `Button` rendered as `<a>`, like the bell.
- The kind pages' row texts are workbook content: `run.api` would keep them in the evidence, and `centrum_self_test.py` rejects evidence with `ROW_MARKER`, so the drive saves the table answer without them.
- The page has no polling (#419): a change in the file shows after a reload or a return to the tab.
- Delete the lock file in `finally`; a leftover `~$…` makes Przebieg rozliczeń stop with „Plik zbiorczy otwarty”.
