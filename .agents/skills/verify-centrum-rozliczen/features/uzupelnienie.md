# Uzupełnienie pliku zbiorczego

After Przygotowanie pliku zbiorczego, Dad types the Ilości do uzupełnienia in
Excel. The card `Następny krok` on Okresy offers `Uzupełnij` for a period with
Plik zbiorczy przygotowany, and it leads to the period's summary at
`#/uzupelnienie/<token>`: a counter „x z y” and the row numbers for `Wiersze bez
reguły` and `Wiersze z opisu` (done rows crossed out, a kind with no rows or
all rows done ticked, never red), how many rows hold a value in each column
from the technician's description, `Otwórz Plik zbiorczy`, and `Gotowe, rozlicz
pracowników`, which opens Przebieg rozliczeń with the period chosen; its
dialog `Uruchomić z zapisem?` lists the rows still without quantity. Centrum reads
the saved Plik zbiorczy on every read, also while Excel holds it, and never
changes it. A Plik zbiorczy it cannot read is a calm three-part Komunikat.

## Sub-features

- `uzupelnienie-karta`: the card `Następny krok` for the last complete period with Status `Plik zbiorczy przygotowany` has `Uzupełnij` as its primary action and `Podgląd bez zapisu` next to it.
- `uzupelnienie-podsumowanie`: `Uzupełnij` opens `#/uzupelnienie/06_12_10_2026` with the period token in the title row; the counters, row numbers and column counters equal `GET /api/periods/<token>/quantities-to-fill`; the sidebar highlights Okresy; the view is measured as page `uzupelnienie`.
- `uzupelnienie-wpis-taty`: one value Dad types in column Y of row 18 (harness, openpyxl) makes, after a reload, row 18 done (`1 z 2`) and column Y count one more row; nothing else changes.
- `uzupelnienie-blokada-excela`: Excel's lock file `~$…` next to the Plik zbiorczy changes neither the server's answer nor the screen.
- `uzupelnienie-otworz`: `Otwórz Plik zbiorczy` opens the period's Plik zbiorczy (`opened.jsonl`).
- `uzupelnienie-powrot`: the link `Okresy` leads back and Wstecz returns to the same summary.
- `uzupelnienie-gotowe`: with Excel closed, `Gotowe, rozlicz pracowników` opens `#/uruchomienia` with Przebieg rozliczeń and `06_12_10_2026` chosen; the setup's `without_quantity` of the period is the summary's rows not done (`[19, 20]`).
- `uzupelnienie-gotowe-potwierdzenie`: `Uruchom` opens `Uruchomić z zapisem?`, which says `2 wiersze bez ilości: 19, 20` and keeps `Uruchom` enabled; `Anuluj` closes it.
- `uzupelnienie-gotowe-bez-odczytu`: with the Plik zbiorczy of `29_05_10_2026` damaged (harness, restored after), `Gotowe` on its summary chooses that period, not the preselected one; the setup still answers with `without_quantity: {state: unread}`, and the dialog says `Nie udało się sprawdzić wierszy bez ilości` with `Uruchom` enabled.
- `uzupelnienie-bez-pliku`: a period without a Plik zbiorczy shows the server's three-part Komunikat (label `Komunikat`), not a failure, and the Centrum log has `uzupelnienie-odczyt-nieudany` with the period.

## How to get to it (user POV)

- Okresy → card `Następny krok` → `Uzupełnij` (when the last complete period has Plik zbiorczy przygotowany).
- The address `#/uzupelnienie/<token>` directly, also after a reload or Wstecz.

## Driving it with Playwright for Python

Preconditions:

- The last complete period `06_12_10_2026` has Status `Plik zbiorczy przygotowany`. In `all` this feature runs right after `przygotowanie-pliku-zbiorczego`; alone, it drives that feature first.
- After Przygotowanie the fixture's Plik zbiorczy has rows 18 and 20 without rule (a device the Reguły ilości do not know) and row 19 from the description (`prewencja`; `DEVICES` in `create_centrum_fixture.py`), none done.

- **Card.** On Okresy, region `Następny krok` shows `06_12_10_2026` and `Utwórz rozliczenia pracowników`, button `Uzupełnij` (an `<a>` rendered as a button) and button `Podgląd bez zapisu`. `GET /api/periods` (`api/uzupelnienie-karta.json`) has the last complete period with `status: collective_file_prepared`. Screenshot `210`.
- **Summary.** Click `Uzupełnij`: the URL ends in `#/uzupelnienie/06_12_10_2026`, heading level 1 `Uzupełnienie pliku zbiorczego`, the token in `main`. `GET /api/periods/06_12_10_2026/quantities-to-fill` (`api/uzupelnienie-podsumowanie.json`) is `ready` with rows `[18, 20]` and `[19]`, none done. Regions `Wiersze bez reguły` and `Wiersze z opisu` each show `<done> z <rows>`, the image `Zrobione` or `Do uzupełnienia` after the kind's `done`, and list items with the row numbers in order (a done row reads `18 zrobiony`; a kind without rows says `Nie ma takich wierszy.`). Region `Kolumny z opisu technika` has one `dt` per column (Y, AB, AD, AJ, AK, AL, AM) and its `dd` `nic nie wpisano`, `wpisane w 1 wierszu` or `wpisane w N wierszach`. The sidebar link `Okresy` has `data-active`. A `pomiar` line with `strona=uzupelnienie` and `getQuantitiesToFill:` reaches the Centrum log. Screenshot `211`.
- **Dad's value.** Harness (labelled in `drive.txt`): openpyxl writes `1` into Y18 of the run's Plik zbiorczy, saves and closes it, with no lock file. `page.reload()`: the answer (`api/uzupelnienie-po-wpisie.json`) has row 18 done, row 20 not, column Y one more row, everything else unchanged; the screen shows `1 z 2` and `18 zrobiony`. Screenshot `212` in the light theme (the drive switches the theme for it and back).
- **Excel's lock.** Write `~$Rozliczenie 06_12_10_2026 - zbiorcze.xlsx` next to the file and reload: the answer (`api/uzupelnienie-blokada-excela.json`) equals the previous one, and so does the screen. Screenshot `213`.
- **Open.** Click `Otwórz Plik zbiorczy`: the last line of `opened.jsonl` is the period's Plik zbiorczy, and the toast names it.
- **Back.** Click link `Okresy` in `main`: heading `Okresy`. `page.go_back()`: heading `Uzupełnienie pliku zbiorczego` again.
- **Gotowe.** Harness: remove the lock file (Dad closed Excel). Click button `Gotowe, rozlicz pracowników` (an `<a>` rendered as a button): the URL ends in `#/uruchomienia`, `Nowe Uruchomienie procesu` is visible, radio `Przebieg rozliczeń` is checked (the form's first process is Przygotowanie), combobox `Okres` shows `06_12_10_2026`. `GET /api/runs/setup` (`api/uzupelnienie-gotowe.json`) has for the period `without_quantity: {state: read, rows: [19, 20]}`, the rows the summary shows not done. Screenshot `215`.
- **Confirm.** Click `Uruchom`: alertdialog `Uruchomić z zapisem?` contains `„Uruchom” potwierdza Gotowość Pliku zbiorczego` and `2 wiersze bez ilości: 19, 20`, and its `Uruchom` is enabled. Screenshot `216`. Click `Anuluj`; nothing runs.
- **Unreadable.** Harness: replace the bytes of `Rozliczenie 29_05_10_2026 - zbiorcze.xlsx` with text (restored in `finally`). Open `#/uzupelnienie/29_05_10_2026` and click `Gotowe`: combobox `Okres` shows `29_05_10_2026`, and `GET /api/runs/setup` (`api/uzupelnienie-gotowe-bez-odczytu.json`) is `200` with `without_quantity: {state: unread}` for it. `Uruchom` opens the dialog with `Nie udało się sprawdzić wierszy bez ilości` and an enabled `Uruchom`. Screenshot `217`. `Anuluj`, then a reload drops the form's draft.
- **Restore.** In `finally` the drive writes back the Plik zbiorczy's original bytes and removes the lock file; the damaged Plik zbiorczy of `29_05_10_2026` gets its bytes back too, because `przebieg-rozliczen` reads it.
- **No Plik zbiorczy.** Open `#/uzupelnienie/15_21_09_2026` (empty Folder okresu): label `Komunikat` shows the answer's `what`, `where` and `action` (`api/uzupelnienie-bez-pliku.json`, `state: problem`), no alert `Nie udało się …`, and the Centrum log has `uzupelnienie-odczyt-nieudany … okres=15_21_09_2026`. Screenshot `214`.
- **Proof.** Screenshots `210`–`217`, `api/uzupelnienie-*.json`, checks in `drive.txt`.

## Gotchas

- Restore the Plik zbiorczy: `przebieg-rozliczen` continues from it, and a value left in Y18 would reach a Rozliczenie pracownika and the Kontrola ilości.
- `Uzupełnij` has role `button`, not `link`: it is a Base UI `Button` rendered as `<a>`, like the bell.
- `Gotowe` only fills the Przebieg form (`setDraft`, in page memory); a reload drops it. The drive reloads after the last `Gotowe` so the next feature starts from the preselected process.
- The rows without quantity are the listed kinds' rows not done (bez reguły and z opisu), never a row the Reguły ilości cover; an unreadable Plik zbiorczy makes them `unread`, and the setup still answers.
- The page has no polling (#419): a change in the file shows after a reload or a return to the tab.
- Delete the lock file in `finally`; a leftover `~$…` makes Przebieg rozliczeń stop with „Plik zbiorczy otwarty”.
