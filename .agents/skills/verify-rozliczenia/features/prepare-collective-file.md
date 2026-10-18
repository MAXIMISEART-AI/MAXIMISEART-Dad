# Przygotowanie pliku zbiorczego

The second process, run before the settlement. From a Rejestr zleceń it creates
the Rozliczenie wewnętrzne and the Plik zbiorczy of one period inside the Folder
okresu, both together or neither. Dad starts it with
`Przygotuj plik zbiorczy.cmd`, which runs `run_preparation.py`.

## Sub-features

- `preparation-plan` dry-run reports the period, order counts, skipped empty rows, orders per day, warnings, and both file names, then `DRY-RUN: Nic nie zapisano`; it creates neither file nor the Folder okresu.
- `preparation-internal` writes every period order (successful or not) in Rejestr order to the Rozliczenie wewnętrzne, with `zwrot`/`UWAGI` empty.
- `preparation-collective` writes every Zlecenie skuteczne to `A:K` from row 18 of the Plik zbiorczy, leaving rates, sums, `N:AP` zeros, formulas, and sheets from the Wzorzec.
- `preparation-formatting` carries fill, font colour, bold, italic, and date format from the Rejestr; font face/size, widths, and frozen header from the Wzorzec; autofilter covers header plus data rows.
- `preparation-links` keeps every `xl/externalLinks/*` part of the Wzorzec pliku zbiorczego byte-identical.
- `preparation-safety` leaves the Rejestr and both Wzorce byte-identical and leaves no staging directory.
- `preparation-metrics` appends to its own history with counters `period_orders`, `successful_orders`, `skipped_empty_rows`, `warnings`.

## How to get to it (user POV)

- Dad double-clicks `Przygotuj plik zbiorczy.cmd`, picks the Rejestr and the periods folder in dialogs, and confirms the proposed period with Enter.
- Direct verification passes every input explicitly, so no dialog or period question appears: `py -3 run_preparation.py --register <rejestr> --periods-directory <folder okresów> --period 08_14_09_2026 --config <mapping> --internal-template <wzorzec> --collective-template <wzorzec> --metrics <metrics> [--dry-run]`.

## Driving it with PowerShell and run.py

Preconditions:

- The orchestrator builds the synthetic Rejestr (decoy `lista` sheet, hidden `ARCHIWUM` sheet with an older order, empty export rows, orders outside the period, a late Monday order, highlights), both Wzorce with an external link, and a three-worker mapping under a fresh run root.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation`. It runs `create_preparation_fixture.py`, `preparation_doctor.py`, the dry-run, `assert_preparation.py --expect dry-run`, the real run, `assert_preparation.py --expect run`, cleanup, and the self-test. Success prints `VERIFY OK | variant=preparation`.
- **Read the counts.** The fixture yields 4 period orders, 3 Zlecenia skuteczne, 5 skipped empty rows (every fully empty row from the first to the last period order, including the two around the next-period order before the late Monday order), orders on Tue, Wed, Sat, and Mon, and 0 warnings. Both runs exit `0`.
- **Read the workbook proof.** `assert-run.txt` confirms both period files, routed values, formatting, autofilters, preserved Wzorzec content, byte-identical external links, unchanged inputs, and two metrics records (`DRY-RUN`, `RUN`).
- **Drive the launcher.** On Windows run `py -3 -m pytest tests/test_cmd_launcher.py -k "przygotowanie or incomplete_period" -q`; it copies `Przygotuj plik zbiorczy.cmd` into a synthetic runtime, checks a successful run, and checks that refusing an incomplete period exits `1` with nothing written.
- **Drive stops and warnings.** The engine and CLI tests (`tests/test_collective_preparation_stops.py`, `tests/test_collective_preparation_cli.py`) cover every stop and warning; `tests/test_instrukcja_taty.py` keeps Dad's "komunikat → co zrobić" table in step with the message catalog.

## Gotchas

- Without `--dry-run`, an incomplete period (last order before the Monday) asks for confirmation after the Planowanie stage, even when `--period` is passed. The orchestrator closes stdin, so such a question ends in refusal and exit `1` instead of a hang; keep a Monday order in the fixture.
- The period token uses the Monday's month and year (`29_05_10_2026`); the Tuesday-month form is rejected.
- An existing Folder okresu is allowed; an existing period file stops the run (Nienadpisywanie).
- The CLI prints no row content; the `PREP-SYN-` markers in the fixture exist so the self-test can catch a leak.
