# Tablica okresów

Okresy shows every Folder okresu from the folder okresów, newest first, with
its Status okresu, its files, the number of Rozliczenia pracowników, and the
next step. The last complete period is highlighted even without a Folder
okresu, and it is the subject of the `Następny krok` card. Period files and
folders open with one click, for paths the server derived itself. The view
follows the disk on every read.

## Sub-features

- `tablica-kolejnosc-i-status`: order, Status okresu, worker-file count, and the highlighted last complete period match the disk.
- `tablica-nastepny-krok`: the `Następny krok` card names the last complete period's next step and its missing Folder okresu.
- `tablica-otwieranie`: file and folder buttons open the server-derived path; a missing file cannot be opened.
- `tablica-podwojne-klikniecie`: Dad's double click (or double tap) and a fast triple click on a file or folder button open it once: one request, one line in `opened.jsonl`, one `Otwieram`.
- `tablica-zmiana-na-dysku`: files added outside Centrum change the Status okresu after a reload and when Dad returns to the tab.
- `tablica-powrot-z-menu`: back on Okresy from the menu, the last board shows at once and is read again: a Rozliczenie pracownika added meanwhile counts.
- `tablica-odczyt-w-tle-nieudany`: when the read behind the last board fails (unreachable server), Okresy shows the Komunikat instead of the old board; the next return to the tab shows the board again.
- `tablica-podpowiedz`: the next-step text and the card's `Podgląd bez zapisu` explain themselves in tooltips that come with the board.
- `tablica-ochrona`: a foreign `Origin` or `Host` is refused and opens nothing.

## How to get to it (user POV)

- Sidebar `Okresy` (the start page, `#/okresy`), once the folder okresów is set.
- Returning to the Centrum tab, or reloading it, refreshes the board.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. If the folder okresów is not set yet, the drive sets it through `Wskaż folder okresów` (see `ustawienia.md`).

- **Order and Status okresu.** Open the URL. `GET /api/periods` (`api/tablica-okresow.json`) lists `06_12_10_2026` (no_period_files, last complete), `29_05_10_2026` (collective_file_prepared), `22_28_09_2026` (worker_settlements_ready, 3), and `15_21_09_2026` (no_period_files); `Archiwum` is absent. Table `Tablica okresów` shows the same rows in the same order, with labels `Brak plików okresu`, `Plik zbiorczy przygotowany`, `Rozliczenia pracowników gotowe`. The first row has `data-state="selected"` and the screen-reader text `ostatni pełny okres`. Every row with a process step has `next_step.preview_hint`; the closed `22_28_09_2026` row has none.
- **Następny krok.** Region `Następny krok` contains `Przygotuj plik zbiorczy`, `06_12_10_2026`, `Brak Folderu okresu`, and button `Podgląd bez zapisu`.
- **Open.** Click buttons `Plik zbiorczy, okres 29_05_10_2026`, `Rozliczenie wewnętrzne, okres 22_28_09_2026`, `Folder okresu, okres 15_21_09_2026`, and `Rozliczenia pracowników: 3, okres 22_28_09_2026`. Each click appends exactly its path under `INEA` to `opened.jsonl` and shows a toast `Otwieram` with the file or folder name. Button `Plik zbiorczy, okres 15_21_09_2026` is disabled.
- **Double click.** Double-click button `Folder okresu, okres 22_28_09_2026` (`dblclick()`), then triple-click `Plik zbiorczy, okres 22_28_09_2026` (`click(click_count=3)`). Each sends one `POST /api/periods/22_28_09_2026/open` (counted with `page.on("request")`), appends its path to `opened.jsonl` once, and region `Notifications` holds one toast `Otwieram` with its name and no error toast. Capture `1a`.
- **Change on disk.** Create both period files in `INEA/15_21_09_2026`, then reload. Row `15_21_09_2026` shows `Plik zbiorczy przygotowany`. Create `Rozliczenie pracowników 15_21_09_2026` in it, then dispatch the window `focus` event that a return to the tab fires. The row shows `Rozliczenia pracowników gotowe`.
- **Tooltip.** Hover `Utwórz rozliczenia pracowników` in row `29_05_10_2026`. The tooltip `Najpierw uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij.` is visible. Hover button `Podgląd bez zapisu` in region `Następny krok`; the tooltip shows that row's `preview_hint`, `Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.`
- **Back from the menu.** Click link `Metryki`, add `Rozliczenie 15_21_09_2026 - Wykonawca.xlsx` to `Rozliczenie pracowników 15_21_09_2026`, click link `Okresy`. Button `Rozliczenia pracowników: 1, okres 15_21_09_2026` appears. Remove the file.
- **Failed read in the background.** Click link `Metryki`, make `/api/periods` fail with `page.route(...).abort()` (harness: the server is unreachable for that read, labelled in `drive.txt`), click link `Okresy`. The alert `Nie udało się odczytać okresów` says `Centrum rozliczeń nie odpowiada.` and table `Tablica okresów` is gone; capture `17`. Remove the route and dispatch the window `focus` event: row `15_21_09_2026` is back.
- **Refusals.** `POST /api/periods/22_28_09_2026/open` with `Origin: http://zly.example` returns `403` (`api/odmowa-obcy-origin.json`), and `GET /api/health` with `Host: zly.example` returns `403` (`api/odmowa-obcy-host.json`). `opened.jsonl` is unchanged.
- **Proof.** Screenshots `06`–`09`, `1a`, and `17`, `state/opened.jsonl`.

## Gotchas

- Tokens sort by the Tuesday's date, not lexically: `06_12_10_2026` is newer than `29_05_10_2026`.
- The open buttons' accessible names include the token and, for Rozliczenia pracowników, the count. A different count changes the name.
- A tooltip needs a 400 ms hover before it appears; later tooltips open instantly. Wait for the tooltip text, not a fixed delay.
- Centrum ignores a repeated open of the same file or folder until 1.5 s after the server's answer, so a step that opens one target twice on purpose waits longer between the clicks.
- The toast covers the bottom-right corner for a few seconds; take full-page screenshots after it is gone, or capture the viewport on purpose (`07`).
- Okresy keeps the last board of the tab: a step that expects the board read again must wait for the new text, since the old board shows first. A reload (`page.goto`) forgets it.
- Headless Chromium keeps every tab visible: `bring_to_front()` fires neither `focus` nor `visibilitychange`. The tab return is therefore simulated with `window.dispatchEvent(new FocusEvent('focus'))`; `drive.txt` labels it as simulated. The reload half is the real user path.
