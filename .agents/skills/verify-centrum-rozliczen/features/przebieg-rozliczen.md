# Przebieg rozliczeń

Dad continues his week from the Plik zbiorczy that Przygotowanie pliku
zbiorczego published: he fills it in Excel, saves and closes it (Gotowość),
then creates the Rozliczenia pracowników from Centrum without pointing to any
file. The Okres list offers only periods with Status okresu `Plik zbiorczy
przygotowany`; `Podgląd bez zapisu` shows the plan per Wykonawca; `Uruchom`,
confirmed in a dialog, is his confirmation of Gotowość. The live view shows
the Szablony pracowników progress, closing Centrum is refused meanwhile, the
Folder rozliczeń pracowników appears at once, and the Status okresu moves to
`Rozliczenia pracowników gotowe`. Every stop and problem has three parts.

## Sub-features

- `przebieg-gotowosc`: the harness fills the Plik zbiorczy of `06_12_10_2026` the way Dad does in Excel (a quantity in N of every Wiersz danych), saves it, and leaves no lock file.
- `przebieg-wybor-okresu`: the board row's next step opens Uruchomienia with tile `Przebieg rozliczeń` chosen, the last complete period preselected, the Plik zbiorczy name in `Pliki`, and the reminder; only periods with a prepared Plik zbiorczy are offered.
- `przebieg-podglad`: `Podgląd bez zapisu` on the `Następny krok` card shows the figures (`Wiersze danych`, `Planowane szablony`, `Puste szablony`) and the open `Plan plików` (one file per Wykonawca with its rows), creates no Folder rozliczeń pracowników, and appends one DRY-RUN record to the CLI's Przebieg rozliczeń metrics file.
- `przebieg-potwierdzenie`: `Uruchom` asks `Uruchomić z zapisem?` with the reminder, the Gotowość line, and no no-preview warning.
- `przebieg-na-zywo`: during the RUN the live view shows `Szablony pracowników · <Wykonawca>` with `x z 3` and the live counters (`Wiersze danych`, `Zapisane szablony`, `Puste szablony`, `Pominięte szablony`, `Problemy`) from the projection, and `POST /api/shutdown` is refused with `409`.
- `przebieg-zapisane`: the result `Rozliczenia pracowników gotowe` with `Zapisane szablony`; the Folder rozliczeń pracowników holds the three files and no staging folder is left; metrics hold RUN OK and DRY-RUN OK marked `centrum`; the Centrum log has the end line; `Folder okresu` opens the Folder okresu.
- `przebieg-status-okresu`: Tablica okresów shows `Rozliczenia pracowników gotowe` and `Następny krok` shows `Okres zamknięty`.
- `przebieg-nienadpisywanie`: a second RUN of the closed period (started through the API, since the Okres list no longer offers it) stops in three parts without a full path and leaves the files byte-identical.
- `przebieg-wymaga-sprawdzenia`: `Podgląd bez zapisu` of `29_05_10_2026`, whose Plik zbiorczy has a Wykonawca missing from the konfiguracja wykonawców, ends `Podgląd wymaga sprawdzenia · nic nie zapisano` with an amber icon, the problem in three parts, and `Uruchom ponownie` instead of `Uruchom`.

## How to get to it (user POV)

- Okresy → card `Następny krok` → `Podgląd bez zapisu` (when the last complete period has Status `Plik zbiorczy przygotowany`).
- Okresy → Tablica okresów → row button `Utwórz rozliczenia pracowników, okres <token>` → Uruchomienia with tile `Przebieg rozliczeń` and that period chosen.
- Sidebar `Uruchomienia` (`#/uruchomienia`) → `Nowe Uruchomienie procesu` → tile `Przebieg rozliczeń`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`.
- `INEA/06_12_10_2026` has both period files from `przygotowanie-pliku-zbiorczego`, with one Zlecenie skuteczne per Wykonawca `wykonawca.a/b/c` (`fixture.json` → `settlement.rows_per_worker`). Run alone (`--feature przebieg-rozliczen`), the drive runs Przygotowanie pliku zbiorczego first.
- `INEA/29_05_10_2026` has a Plik zbiorczy with a Wiersz danych of `wykonawca.a` and one of a Wykonawca the konfiguracja wykonawców does not know (`fixture.json` → `settlement.needs_check`).
- `serve_centrum.py` paces each Szablon pracownika by the milliseconds in `<root>/pacing/szablony-ms.txt` while that file exists; the drive writes it only for the observed RUN and removes it in `finally`.

- **Gotowość.** The drive fills the Plik zbiorczy with openpyxl (`_fill_readiness`), as Dad would in Excel; the check line names it as simulated. No `~$` file is left.
- **Choose the period.** On Okresy click button `Utwórz rozliczenia pracowników, okres 06_12_10_2026`. Radio `Przebieg rozliczeń` is checked, combobox `Okres` shows `06_12_10_2026 · ostatni pełny`, group `Plik zbiorczy` shows `Rozliczenie 06_12_10_2026 - zbiorcze.xlsx`, and `Zapisz i zamknij Plik zbiorczy w Excelu` is visible. `GET /api/runs/setup` (`api/przebieg-wybor-okresu.json`) offers `06_12_10_2026` and `29_05_10_2026` only.
- **Preview.** Back on Okresy click region `Następny krok` → button `Podgląd bez zapisu`. Region `Podgląd na żywo` shows `Podgląd gotowy · nic nie zapisano`; table `Plan plików` has three rows, the first with `1 wiersz`. `GET /api/runs/current` has the planned files in `result.summary.file_plan`; `Rozliczenie pracowników 06_12_10_2026` does not exist; `/api/metrics` has one more Przebieg rozliczeń record, a DRY-RUN.
- **Confirm.** Click `Uruchom` in the result banner. Alertdialog `Uruchomić z zapisem?` shows the reminder and `„Uruchom” potwierdza Gotowość Pliku zbiorczego`, without `Nie było podglądu bez zapisu`. The drive writes the pacing file, then clicks the dialog's `Uruchom`.
- **Live.** Progressbar `Szablony pracowników` is visible with `Szablony pracowników · Wykonawca Testowy A`, and the counters strip (`dl` with `aria-label="Liczniki"`) shows `Zapisane szablony 0`. When the progress moves on to `Wykonawca Testowy B`, the strip shows `Zapisane szablony 1` and `Wiersze danych` equal to the `Wiersze danych` figure in `progress.figures` of `GET /api/runs/current` (`running`, `template_total: 3`, `Zapisane szablony` figure `1`); `POST /api/shutdown` with Centrum's `Origin` returns `409` (`api/przebieg-zamkniecie-odmowa.json`). Screenshot `43` is taken without waiting for animations (the running stage's bar loops).
- **Saved.** Label `Wynik` shows `Rozliczenia pracowników gotowe`; the Folder rozliczeń pracowników has the three files and the Folder okresu holds only the two period files and that folder; the two newest Przebieg rozliczeń records are RUN OK and DRY-RUN OK with `origin: centrum`; the Centrum log has `uruchomienie-koniec proces=settlement tryb=RUN okres=06_12_10_2026 wynik=OK koniec=finished`. Button `Folder okresu` appends the Folder okresu to `opened.jsonl`.
- **Status okresu.** On Okresy the row `06_12_10_2026` shows `Rozliczenia pracowników gotowe`, region `Następny krok` shows `Okres zamknięty`, and `/api/periods` has `worker_settlement_count: 3`.
- **Nienadpisywanie.** `POST /api/runs` RUN for `06_12_10_2026` (`api/przebieg-nienadpisywanie-start.json`), then `#/uruchomienia`: label `Zatrzymanie` shows `Folder rozliczeń pracowników tego okresu już istnieje, więc nie został nadpisany.` and `folder 06_12_10_2026\Rozliczenie pracowników 06_12_10_2026`; the result holds no run-root path; the three files keep their bytes.
- **Needs checking.** Click `Nowe Uruchomienie procesu`, radio `Przebieg rozliczeń` (combobox `Okres` now shows `29_05_10_2026`), and `Podgląd bez zapisu`. Label `Wynik` shows `Podgląd wymaga sprawdzenia · nic nie zapisano` with button `Uruchom ponownie`; label `Ostrzeżenie` shows `Nieznany identyfikator WYKONAWCA`; the result is `WYMAGA_SPRAWDZENIA` with `next_action: rerun`; nothing is written.
- **Proof.** Screenshots `40`–`47`, `api/przebieg-*.json`, checks in `drive.txt`.

## Gotchas

- The counters strip is a description list, not a landmark; find it with `live.locator('dl[aria-label="Liczniki"]')`. Its text joins label and value without a space (`Zapisane szablony1`).
- Without the pacing file the synthetic RUN ends in milliseconds: the live progress cannot be seen, and a `POST /api/shutdown` sent after the end really closes Centrum. Keep the pacing on until the refusal is recorded.
- After the RUN, `06_12_10_2026` leaves the Okres list (its Status okresu is `Rozliczenia pracowników gotowe`); the Nienadpisywanie step therefore starts through the API, as a second tab or a stale page would.
- `Plan plików` is open after a preview and folded after a RUN.
- The result toast covers the bottom-right corner for a few seconds after a RUN.
- `Uruchom` is also the confirmation dialog's button; scope the second click to the alertdialog.
