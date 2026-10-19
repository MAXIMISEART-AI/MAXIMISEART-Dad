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
  `INEA` holds `29_05_09_2026` (Plik zbiorczy przygotowany), `22_28_09_2026`
  (Rozliczenia pracowników gotowe, three files), `15_21_09_2026` (empty Folder
  okresu), and `Archiwum` (not a period).
- `<root>/metrics/` holds both metrics files in the CLI's schema: 16 valid
  synthetic Uruchomienia procesu (Przygotowanie pliku zbiorczego: 6 completed
  RUN, 1 interrupted RUN, 3 DRY-RUN; Przebieg rozliczeń: 5 RUN, one of them
  WYMAGA_SPRAWDZENIA, 1 DRY-RUN) and one record per file that the reader skips.
- The synthetic Rejestr zleceń has four orders in `06_12_10_2026`, the last on
  Saturday, so a RUN of Przygotowanie pliku zbiorczego asks about an
  incomplete period; its order cells carry the row marker.
  Centrum reads these, never the tool's own history.
- No settings are set when a run starts.
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

When a slice adds a feature, add its file here, a `drive_<feature>` function and
entry in `drive_centrum.py`, and its screenshots in
`REQUIRED_SCREENSHOTS` of `run_centrum_verification.py`, in the same PR.

## Features

- [Ustawienia](./ustawienia.md) covers pointing to the folder okresów and the Rejestr zleceń through the native picker, cancelling, a remembered path that is gone, and the remembered theme.
- [Konfiguracja](./konfiguracja.md) covers the read-only view of the three Wzorce, the Wykonawcy from the konfiguracja wykonawców, and the tool version, with a Wzorzec open in Excel, a missing Wzorzec, a broken konfiguracja wykonawców, and proof that Centrum changes none of these files.
- [Tablica okresów](./tablica-okresow.md) covers the period list with Status okresu, the last complete period and Następny krok, opening period files and folders, refreshing after changes on disk, and refusing foreign requests.
- [Metryki](./metryki.md) covers the key numbers on Okresy, P50/P95 and the result distribution per process and mode, the stage-times chart and table, interrupted runs, the history table with sorting and filters, a CLI record appearing without a restart, and the empty state.
- [Przygotowanie pliku zbiorczego](./przygotowanie-pliku-zbiorczego.md) covers choosing the period, Podgląd bez zapisu (DRY-RUN) without writing, the confirmed RUN, the live stages, the incomplete-period decision (abort and continue, surviving a reload), refusing a second Uruchomienie, the three-part stop, Nienadpisywanie, the Status okresu afterwards, the records in the CLI's metrics file, and the Historia tab marking Centrum runs.
- [Start i zamykanie](./start-i-zamykanie.md) covers readiness, the second start that only opens the tab, the three-part message for a port held by another program, the Centrum log, and closing Centrum from the sidebar. It closes the server, so it runs last.
