# Uzupełnienie pliku zbiorczego

After Przygotowanie pliku zbiorczego, Dad types the Ilości do uzupełnienia in
Excel. Three entries lead to the period's summary: the card `Następny krok` on
Okresy and the Tablica okresów row offer `Uzupełnij` for a period with Plik
zbiorczy przygotowany, and the written Plik zbiorczy's result card shows the
same summary with `Uzupełnij`. Droga okresu has `Uzupełnienie w Excelu` as its
current step. The summary is at
`#/uzupelnienie/<token>`: a counter „x z y” and the row numbers for `Wiersze bez
reguły` and `Wiersze z opisu` (done rows crossed out, a kind with no rows or
all rows done ticked, never red), how many rows hold a value in each column
from the technician's description, and `Otwórz Plik zbiorczy` when the Plik
zbiorczy is in the Folder okresu. Centrum reads
the saved Plik zbiorczy on every read, also while Excel holds it, and never
changes it. A Plik zbiorczy it cannot read is a calm three-part Komunikat.

## Sub-features

- `uzupelnienie-wynik`: the result card of Przygotowanie z zapisem has region `Uzupełnienie pliku zbiorczego` with the summary of `GET /api/periods/<token>/quantities-to-fill` and `Uzupełnij`, which opens the same summary; Wstecz returns to the result. Driven from `przygotowanie-kontynuuj`, the only written Przygotowanie without a stop.
- `uzupelnienie-tablica`: only the Tablica okresów row with Status `Plik zbiorczy przygotowany` has `Uzupełnij, okres <token>`, and it opens that period's summary.
- `uzupelnienie-droga`: Droga okresu on `Następny krok` has one current step (`aria-current="step"`), `Uzupełnienie w Excelu`, after one done step.
- `uzupelnienie-karta`: the card `Następny krok` for the last complete period with Status `Plik zbiorczy przygotowany` has `Uzupełnij` as its primary action and `Podgląd bez zapisu` next to it.
- `uzupelnienie-podsumowanie`: `Uzupełnij` opens `#/uzupelnienie/06_12_10_2026` with the period token in the title row; the counters, row numbers and column counters equal `GET /api/periods/<token>/quantities-to-fill`; the sidebar highlights Okresy; the view is measured as page `uzupelnienie`.
- `uzupelnienie-wpis-taty`: one value Dad types in column Y of row 18 (harness, openpyxl) makes, after a reload, row 18 done (`1 z 2`) and column Y count one more row; nothing else changes.
- `uzupelnienie-blokada-excela`: Excel's lock file `~$…` next to the Plik zbiorczy changes neither the server's answer nor the screen.
- `uzupelnienie-otworz`: `Otwórz Plik zbiorczy` opens the period's Plik zbiorczy (`opened.jsonl`).
- `uzupelnienie-powrot`: the link `Okresy` leads back and Wstecz returns to the same summary.
- `uzupelnienie-bez-pliku`: a period without a Plik zbiorczy shows the server's three-part Komunikat (label `Komunikat`), not a failure, `Otwórz Plik zbiorczy` only when the file is in the Folder okresu (`collective_file_exists`), and the Centrum log has `uzupelnienie-odczyt-nieudany` with the period.

## How to get to it (user POV)

- Okresy → card `Następny krok` → `Uzupełnij` (when the last complete period has Plik zbiorczy przygotowany).
- Okresy → Tablica okresów → `Uzupełnij` in the row of any period with Plik zbiorczy przygotowany.
- Uruchomienia → result of Przygotowanie pliku zbiorczego z zapisem → `Uzupełnij`.
- The address `#/uzupelnienie/<token>` directly, also after a reload or Wstecz.

## Driving it with Playwright for Python

Preconditions:

- The last complete period `06_12_10_2026` has Status `Plik zbiorczy przygotowany`. In `all` this feature runs right after `przygotowanie-pliku-zbiorczego`; alone, it drives that feature first.
- After Przygotowanie the fixture's Plik zbiorczy has rows 18 and 20 without rule (a device the Reguły ilości do not know) and row 19 from the description (`prewencja`; `DEVICES` in `create_centrum_fixture.py`), none done.

- **Result card.** In `przygotowanie-kontynuuj` the region `Podgląd na żywo` has region `Uzupełnienie pliku zbiorczego` with heading `Do uzupełnienia w Excelu`; inside it the kind regions and `Kolumny z opisu technika` equal `api/uzupelnienie-wynik.json` exactly as on the summary page (one rendering, one resource). Screenshot `230`. Click its `Uzupełnij`: the URL ends in `#/uzupelnienie/06_12_10_2026` with the same counters; `page.go_back()` shows the result again.
- **Tablica okresów.** On Okresy, row `06_12_10_2026` shows `Plik zbiorczy przygotowany` and button `Uzupełnij, okres 06_12_10_2026` (an `<a>`); the table has as many `Uzupełnij, okres …` buttons as `GET /api/periods` (`api/uzupelnienie-tablica.json`) has periods with `status: collective_file_prepared` (the fixture has two: `06_12_10_2026` and `29_05_10_2026`), each in its own row. Screenshot `231`. The click opens the summary (`api/uzupelnienie-z-tablicy.json`).
- **Droga okresu.** `page.go_back()` to Okresy: list `Droga okresu` in `Następny krok` has one item with `aria-current="step"`, `Uzupełnienie w Excelu`, and one image `zrobione`.
- **Card.** On Okresy, region `Następny krok` shows `06_12_10_2026` and `Utwórz rozliczenia pracowników`, button `Uzupełnij` (an `<a>` rendered as a button) and button `Podgląd bez zapisu`. `GET /api/periods` (`api/uzupelnienie-karta.json`) has the last complete period with `status: collective_file_prepared`. Screenshot `220`.
- **Summary.** Click `Uzupełnij`: the URL ends in `#/uzupelnienie/06_12_10_2026`, heading level 1 `Uzupełnienie pliku zbiorczego`, the token in `main`. `GET /api/periods/06_12_10_2026/quantities-to-fill` (`api/uzupelnienie-podsumowanie.json`) is `ready` with rows `[18, 20]` and `[19]`, none done. Regions `Wiersze bez reguły` and `Wiersze z opisu` each show `<done> z <rows>`, the image `Zrobione` or `Do uzupełnienia` after the kind's `done`, and list items with the row numbers in order (a done row reads `18 zrobiony`; a kind without rows says `Nie ma takich wierszy.`). Region `Kolumny z opisu technika` has one `dt` per column (Y, AB, AD, AJ, AK, AL, AM) and its `dd` `nic nie wpisano`, `wpisane w 1 wierszu` or `wpisane w N wierszach`. The sidebar link `Okresy` has `data-active`. A `pomiar` line with `strona=uzupelnienie` and `getQuantitiesToFill:` reaches the Centrum log. Screenshot `221`.
- **Dad's value.** Harness (labelled in `drive.txt`): openpyxl writes `1` into Y18 of the run's Plik zbiorczy, saves and closes it, with no lock file. `page.reload()`: the answer (`api/uzupelnienie-po-wpisie.json`) has row 18 done, row 20 not, column Y one more row, everything else unchanged; the screen shows `1 z 2` and `18 zrobiony`. Screenshot `222` in the light theme (the drive switches the theme for it and back).
- **Excel's lock.** Write `~$Rozliczenie 06_12_10_2026 - zbiorcze.xlsx` next to the file and reload: the answer (`api/uzupelnienie-blokada-excela.json`) equals the previous one, and so does the screen. Screenshot `223`.
- **Open.** Click `Otwórz Plik zbiorczy`: the last line of `opened.jsonl` is the period's Plik zbiorczy, and the toast names it.
- **Back.** Click link `Okresy` in `main`: heading `Okresy`. `page.go_back()`: heading `Uzupełnienie pliku zbiorczego` again.
- **Restore.** In `finally` the drive writes back the Plik zbiorczy's original bytes and removes the lock file.
- **No Plik zbiorczy.** Open `#/uzupelnienie/15_21_09_2026` (empty Folder okresu): label `Komunikat` shows the answer's `what`, `where` and `action` (`api/uzupelnienie-bez-pliku.json`, `state: problem`), no alert `Nie udało się …`; `collective_file_exists` and the button `Otwórz Plik zbiorczy` follow the disk (alone: no file, no button; in `all`, `tablica-okresow` left an empty `Rozliczenie 15_21_09_2026 - zbiorcze.xlsx`, so the Komunikat calls it damaged and the button is there), and the Centrum log has `uzupelnienie-odczyt-nieudany … okres=15_21_09_2026`. Screenshot `224`.
- **Proof.** Screenshots `220`–`224`, `230`, `231`, `api/uzupelnienie-*.json`, checks in `drive.txt`.

## Gotchas

- Restore the Plik zbiorczy: `przebieg-rozliczen` continues from it, and a value left in Y18 would reach a Rozliczenie pracownika and the Kontrola ilości.
- `Uzupełnij` has role `button`, not `link`: it is a Base UI `Button` rendered as `<a>`, like the bell.
- The page has no polling (#419): a change in the file shows after a reload or a return to the tab.
- Delete the lock file in `finally`; a leftover `~$…` makes Przebieg rozliczeń stop with „Plik zbiorczy otwarty”.
