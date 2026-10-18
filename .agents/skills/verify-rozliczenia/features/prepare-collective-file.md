# Przygotowanie pliku zbiorczego

The second process, run before the settlement. From a Rejestr zleceń it creates
the Rozliczenie wewnętrzne and the Plik zbiorczy of one period inside the Folder
okresu, both together or neither. Dad starts it with
`Przygotuj plik zbiorczy.cmd`, which runs `run_preparation.py`.

## Sub-features

- `preparation-plan` dry-run reports the period, order counts, skipped empty rows, orders per day, warnings, and both file names, then `DRY-RUN: Nic nie zapisano`; it creates neither file nor the Folder okresu.
- `preparation-internal` writes every period order (successful or not) in Rejestr order to the Rozliczenie wewnętrzne, with `zwrot`/`UWAGI` empty.
- `preparation-collective` writes every Zlecenie skuteczne to `A:K` from row 18 of the Plik zbiorczy, leaving rates, sums, `N:AP` zeros, formulas, and sheets from the Wzorzec.
- `preparation-formatting` carries fill, font colour, bold, italic, and number format (dates included) from the Rejestr; widths and frozen header from the Wzorzec; font face/size from the Wzorzec cell, else its row style, else its column style; autofilter covers header plus data rows.
- `preparation-links` keeps every `xl/externalLinks/*` part of the Wzorzec pliku zbiorczego byte-identical.
- `preparation-safety` leaves the Rejestr and both Wzorce byte-identical and leaves no staging directory.
- `preparation-real-templates` (local only) runs the same Rejestr into copies of the real Wzorce from `config/`: data font equals the header font, Wzorzec cells outside the written rows are unchanged, Wzorce and external links are byte-identical.
- `preparation-metrics` appends to its own history with counters `period_orders`, `successful_orders`, `skipped_empty_rows`, `warnings`.

## How to get to it (user POV)

- Dad double-clicks `Przygotuj plik zbiorczy.cmd`, picks the Rejestr and the periods folder in dialogs, and confirms the proposed period with Enter.
- Direct verification passes every input explicitly, so no dialog or period question appears: `py -3 run_preparation.py --register <rejestr> --periods-directory <folder okresów> --period 08_14_09_2026 --config <mapping> --internal-template <wzorzec> --collective-template <wzorzec> --metrics <metrics> [--dry-run]`.

## Driving it with PowerShell and run.py

Preconditions:

- The orchestrator builds the synthetic Rejestr (decoy `lista` sheet, hidden `ARCHIWUM` sheet with an older order, empty export rows, orders outside the period, a late Monday order, highlights), both Wzorce (the Wzorzec pliku zbiorczego with an external link), and a three-worker mapping under a fresh run root.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation`. It runs `create_preparation_fixture.py`, `preparation_doctor.py`, the dry-run, `assert_preparation.py --expect dry-run`, the real run, `assert_preparation.py --expect run`, cleanup, and the self-test. Success prints `VERIFY OK | variant=preparation`.
- **Read the counts.** The fixture yields 5 period orders, 4 Zlecenia skuteczne, 4 skipped empty rows (every fully empty row from the first to the last period order, including the one before the next-period order), orders on Tue, Wed, Sat, Sun, and Mon, and 0 warnings. Adrian's Sunday order sits after the next-period order, so his two Zlecenia skuteczne are split by Kamil's in the Plik zbiorczy. Both runs exit `0`.
- **Read the workbook proof.** `assert-run.txt` confirms both period files, routed values, formatting, autofilters, preserved Wzorzec content, byte-identical external links, unchanged inputs, and two metrics records (`DRY-RUN`, `RUN`).
- **Check the real Wzorce.** When `config/` holds both Wzorce, run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation-real-templates` (in a worktree add `--templates-dir <main checkout>\config`). Counts and summary match `preparation`; `assert-run.txt` ends with `templates=config`. A failure names the column and both fonts, never a cell value.
- **Drive the launcher.** On Windows run `py -3 -m pytest tests/test_cmd_launcher.py -k "przygotowanie or incomplete_period" -q`; it copies `Przygotuj plik zbiorczy.cmd` into a synthetic runtime, checks a successful run, and checks that refusing an incomplete period exits `1` with nothing written.
- **Drive stops, warnings, and the row-style font.** The variant fixture reaches none of these; prove them with `py -3 -m pytest tests/test_collective_preparation.py tests/test_collective_preparation_stops.py tests/test_collective_preparation_cli.py -q`. They cover every stop and warning, including:
  - Wzorzec checks (missing, open in Excel, damaged, wrong header, WYKONAWCA outside H17 in the Wzorzec pliku zbiorczego) in Sprawdzanie, before the Rejestr is read, also in `--dry-run`;
  - merged Wzorzec cells in the rows orders will fill, which stop the run in Planowanie;
  - the "too few zero rows" warning, which still exits `0` and writes both files;
  - the row-style font fallback (`test_cells_without_own_style_take_wzorzec_row_font_before_column_font`).

  `tests/test_instrukcja_taty.py` keeps Dad's "komunikat → co zrobić" table in step with the message catalog.

## Gotchas

- Without `--dry-run`, an incomplete period (last order before the Monday) asks for confirmation after the Planowanie stage, even when `--period` is passed. The orchestrator closes stdin, so such a question ends in refusal and exit `1` instead of a hang; keep a Monday order in the fixture.
- The period token uses the Tuesday's month and year (`27_02_10_2026`, `29_04_12_2026`); the Monday-month form is rejected.
- An existing Folder okresu is allowed; an existing period file stops the run (Nienadpisywanie).
- The CLI prints no row content; the `PREP-SYN-` markers in the fixture exist so the self-test can catch a leak.
- The synthetic Wzorce do not reproduce every style layer of the real ones. Before #66 the code skipped the row style of the real Wzorzec rozliczenia wewnętrznego and wrote Calibri 11 instead of 10; `--variant preparation` passed, only `preparation-real-templates` failed. Run it after any change to how template styles are applied.
