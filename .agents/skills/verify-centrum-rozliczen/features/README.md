# Centrum rozliczeń verification map

This directory is the maintained source for verifying what Dad can do in
Centrum rozliczeń. Read this index before driving, then use the matching
feature file as the recipe.

## Baseline preconditions

- The built frontend in `src/rozliczenia/centrum/static/` matches `frontend/`
  (`npm run build` in `frontend/` after any frontend change).
- Playwright for Python and Chromium are installed (see `SKILL.md`, Launch).
- `run_centrum_verification.py` created a fresh run root with
  `create_centrum_fixture.py`, `serve_centrum.py` is serving it, and
  `centrum_doctor.py` reported `DOCTOR OK`.
- The fixture's "today" is Monday `2026-10-19`, so the last complete period is
  `06_12_10_2026`, whose Folder okresu does not exist. The folder okresów
  `INEA` holds `29_05_10_2026` (Plik zbiorczy przygotowany; its Plik zbiorczy
  has a Wykonawca missing from the konfiguracja wykonawców), `22_28_09_2026`
  (Rozliczenia pracowników gotowe, three files), `15_21_09_2026` (empty Folder
  okresu), and `Archiwum` (not a period).
- `<root>/Załączniki` holds Dad's layout for `uklad-folderow-taty`: weeks in
  `Rozliczenia 2026\{miesiąc}\INEA` of September, October, and November, with
  `06_12_10_2026` and `29_05_10_2026` prepared in October.
- `<root>/metrics/` holds both metrics files in the CLI's schema: 16 valid
  synthetic Uruchomienia procesu (Przygotowanie pliku zbiorczego: 6 completed
  RUN, 1 interrupted RUN, 3 DRY-RUN; Przebieg rozliczeń: 5 RUN, one of them
  WYMAGA_SPRAWDZENIA, 1 DRY-RUN) and one record per file that the reader skips.
- The synthetic Rejestr zleceń has four orders in `06_12_10_2026`, the last on
  Saturday, so a RUN of Przygotowanie pliku zbiorczego asks about an
  incomplete period; its order cells carry the row marker.
  Centrum reads these, never the tool's own history.
- No settings are set when a run starts.
- Only for `wydajnosc`, the fixture is created with `--wariant rok-pracy`: `<root>/Rok pracy/Załączniki` holds 52 periods in Dad's layout and the metrics files hold a year of records (see `wydajnosc.md`).
- `<root>/aktualizacja/` holds the run's tool for `aktualizacja`: a clone (`klon`) on the first synthetic commit and a bare local "origin" (`origin.git`) one commit ahead. Centrum's own commit is the clone's `HEAD`, and Aktualizacja narzędzia moves only this clone. The clone's `run_centrum.py` serves the run's scripted Centrum, so the Centrum the restart guardian starts after an update is again this run's.
- The run's `config/` holds a synthetic `worker_mapping.yaml` (three Wykonawcy)
  and the three Wzorce, valid for the engine's Sprawdzanie; Konfiguracja reads
  these, never Dad's `config/`.

## Driving conventions

- Drive through the browser with `drive_centrum.py`. Find elements by ARIA role
  and accessible name; the names are Polish UI text, so copy them exactly
  (`exact=True`: Playwright otherwise matches case-insensitive substrings, and
  `Wskaż folder okresów` differs from `Wskaż Folder okresów` only in case).
- Answer a native picker by writing the path to `<root>/picker/answer.txt`
  before the click. Leave the file absent to cancel.
- Read side effects from the run root: `config/centrum-ustawienia.yaml`,
  `dialogs.jsonl`, and `opened.jsonl`.
- Change files on disk only inside the run root, and restore what a step moved.
- Capture with `Run.capture`, which waits for running transitions; a screenshot
  taken mid-transition shows content at partial opacity.

## Proof and skip reporting

- Every step records its action, the screen (`screenshots/`, `aria/`), the
  server's answer (`api/`), and the side effect on disk (`state/`, checks in
  `drive.txt`).
- Report a feature as verified only when its steps ran in this run. A feature
  left out with `--feature` is a skip; report it as one.
- `VERIFY FAIL` keeps `screenshots/zz-failure.png` and the evidence of every
  step before the failure.
- Evidence contains synthetic paths only; workbook content never appears.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the user-visible
behaviour, then exactly these H2s in order:

1. `Sub-features`: short IDs with one line each; the IDs match the
   `STEP <feature> | <id>` lines in `drive.txt`.
2. `How to get to it (user POV)`: every entry point Dad has.
3. `Driving it with Playwright for Python`: starts with `Preconditions:`, then
   labelled bullets pairing each action with the exact handle and the
   observable result.
4. `Gotchas`: traps that waste or invalidate a run.

When a slice adds a feature, add its file here, its module in `scripts/drive/` and an
entry in `drive_centrum.py`, and its screenshots in
`REQUIRED_SCREENSHOTS` of `run_centrum_verification.py`, in the same PR.

## Features

- [Ustawienia](./ustawienia.md) covers pointing to the folder okresów and the Rejestr zleceń through the native picker, one picker at a time (also for a double click), cancelling, a remembered path that is gone, and the remembered theme.
- [Układ folderów taty](./uklad-folderow-taty.md) covers pointing to `Załączniki` with weeks in `Rozliczenia {rok}\{miesiąc}\INEA`: weeks from every month on the board, Następny krok for the prepared last complete period, opening a file from its month folder, and restoring the flat folder.
- [Konfiguracja](./konfiguracja.md) covers the read-only view of the three Wzorce, the Wykonawcy from the konfiguracja wykonawców, and the tool version, with a Wzorzec open in Excel, a missing Wzorzec, a broken konfiguracja wykonawców, and proof that Centrum changes none of these files.
- [Tablica okresów](./tablica-okresow.md) covers the period list with Status okresu, the last complete period and Następny krok, opening period files and folders (once for a double or triple click), refreshing after changes on disk, and refusing foreign requests.
- [Aktualizacja narzędzia](./aktualizacja.md) covers the card `Narzędzie` on Konfiguracja with the run's synthetic tool clone and its local "origin": a newer version shown with the clone's commit, the progress after a double click that starts one update with a second update and closing refused, Centrum closing itself and the tab waiting with `Ponowne uruchamianie Centrum…`, the tab reloading by itself on the new Centrum in the new commit with `Zaktualizowano`, the clone moved forward, Dad's `config/` untouched and both commits in the log, and `Masz najnowszą wersję.` when nothing changed. It never reaches GitHub.
- [Metryki](./metryki.md) covers the key numbers on Okresy, P50/P95 and the result distribution per process and mode, the stage-times chart and table, interrupted runs, the history table with sorting and filters, a CLI record appearing without a restart, and the empty state.
- [Przygotowanie pliku zbiorczego](./przygotowanie-pliku-zbiorczego.md) covers choosing the period, Podgląd bez zapisu (DRY-RUN) without writing, the confirmed RUN, the live stages, the incomplete-period decision (abort and continue, surviving a reload), refusing a second Uruchomienie, double clicks that start or decide once without an error toast, the three-part stop, Nienadpisywanie, the Status okresu afterwards, the records in the CLI's metrics file, and the Historia tab marking Centrum runs.
- [Przebieg rozliczeń](./przebieg-rozliczen.md) continues Dad's path from the Plik zbiorczy of Przygotowanie: Gotowość in Excel (simulated), choosing the period without a file, Podgląd bez zapisu with the plan per Wykonawca, the RUN confirmed as Gotowość with the live Szablony pracowników progress and closing refused, the Folder rozliczeń pracowników published at once, the Status okresu `Rozliczenia pracowników gotowe`, Nienadpisywanie, and a preview that needs checking.
- [Diagnoza](./diagnoza.md) covers the kind of stop: a stop Dad fixes himself with `Uruchom ponownie`, the same Komunikat again offering `Diagnoza`, the read-only Diagnoza explaining the cause with `Uruchom ponownie` first and every check listed, a different Komunikat after the fix, a stop „do Maksa” offering `Diagnoza` at once (with a newer `main` only proposed under the confirmation), „Nie znalazłem przyczyny na tym komputerze” when every check passes, and a nieoczekiwany wyjątek that the automatic Diagnoza hits too, leaving one check `nie sprawdzono` and `Wyślij do Maksa` working.
- [Aktualność narzędzia i OneDrive](./aktualnosc-i-onedrive.md) covers the two Diagnoza checks beyond Dad's files with the scripted GitHub and OneDrive of `serve_centrum.py`: a newer `main` explaining the stop with `Uruchom ponownie` only when nothing else is wrong, no network leaving the freshness unchecked and no cause, a Rejestr zleceń only in the cloud explaining „Zawsze zachowuj na tym urządzeniu”, the newer `main` next to it only as a quiet proposal, and both checks passing.
- [Zgłoszenie](./zgloszenie.md) covers sending the Zgłoszenie to Maks from under the Diagnoza: the exact preview under `Co zostanie wysłane`, no key saving it as a file with `Spróbuj ponownie`, the key state on Konfiguracja, sending to the file skrzynka Zgłoszeń with the confirmation, the confirmation after a reload, the same problem in the next Uruchomienie shown as already sent and waiting for the fix, a new Zgłoszenie linking the closed one, and another problem sent separately.
- [Powiadomienie o naprawie](./powiadomienie-o-naprawie.md) covers the notice on Okresy when Maks closes a Zgłoszenie sent from the running version: none while it is open, at most one question to the skrzynka per 10 minutes, no network passing silently, the notice after closing, and the notice gone after an update.
- [Pomiar u taty](./pomiar-u-taty.md) covers the silent measurement: `Server-Timing` on every API answer, one `pomiar` entry in the Centrum log per cold start of each page and per menu click with the server time of every API request, no trace in the UI, no path or period token in the log, and a measurement from a foreign `Origin` refused.
- [Wydajność](./wydajnosc.md) measures Centrum on Dad's year of work in his laptop's CPU profiles (4× and 6×): cold start, reopening the tab, sidebar laps with the visible skeleton time (none in the second lap), interactions, API requests per scenario, bundle size, and CPU traces, against the baseline in `wydajnosc-baseline.json`. Only with `--feature wydajnosc`, never in `all`.
- [Start i zamykanie](./start-i-zamykanie.md) covers readiness, the second start that only opens the tab, the three-part message for a port held by another program, many tabs that keep working because a tab in the background gives back its connection, the Centrum log, and closing Centrum from the sidebar. It closes the server, so it runs last.
