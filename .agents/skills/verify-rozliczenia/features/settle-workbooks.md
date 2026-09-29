# Worker settlement

Worker settlement creates one workbook per configured worker from the shared
Placeholder, copies only the current-period source values into the matching
workbook, and leaves a worker with no rows empty.

## Sub-features

- `settle-map` maps source `WYKONAWCA` identifiers to exact template names.
- `settle-copy` writes source values into `A:AT` starting at row 18.
- `settle-preserve` keeps the template `AU` formulas and structure.
- `settle-empty` leaves a mapped worker with no rows as `PUSTY_SZABLON`.
- `settle-roster` creates exactly one workbook for every configured worker.

## How to get to it (user POV)

- Run the direct CLI command `py -3 run.py --source <source> --config <mapping> --placeholder <placeholder> --metrics <metrics>`.
- Pass the source path to `Utwórz rozliczenia.cmd`.
- In desktop Excel, click the button assigned to `UruchomRozliczenia` in `AutomatyzacjaRozliczen.xlsm`.

## Driving it with PowerShell and run.py

Preconditions:

- Run the one-command orchestrator from the repository root.
- Its default fixture contains mapped rows for Adrian Maciejewski and Darek Nowak and no rows for Kamil Frontczak. The output folder is absent before the run.

- **Run the real user path.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. The application dry-run and write both return `0` for the default fixture.
- **Observe progress.** Read `run.txt`; it reaches `Postęp szablonów: 3/3 (100%)`, reports two `ZAPISANO` results and one `PUSTY_SZABLON`, and ends with `Zapisane szablony: 2`.
- **Verify workbook state.** Read `assert-run.txt`; it returns `ASSERT OK` with exit code `0` after checking exactly three files, routed values, preserved formulas/sheets/formatting, an empty Kamil workbook, and an untouched Placeholder.
- **Drive the CMD adapter when needed.** Use a new fixture and run `cmd /c "Utwórz rozliczenia.cmd" "$source"`; use repository mapping names and expect the same engine semantics. Do not use a populated fixture for this second drive.
- **Drive the VBA adapter when needed.** Open `AutomatyzacjaRozliczen.xlsm`, invoke `UruchomRozliczenia`, choose the synthetic source, and inspect the same output files. This is an Excel-only manual path, not a headless assertion.

## Gotchas

- The source file must be named `Rozliczenie 08_14_09_2026 - zbiorcze.xlsx` and live under a folder named `08_14_09_2026`.
- The configured shared Placeholder is copied into each new workbook and is
  never modified. The final output folder appears only after all files are ready.
- The proof must inspect formulas with `data_only=False`; cached formula results are not the template-preservation proof.
- An unmapped WYKONAWCA stops the real run before creating the output folder;
  verify that path with `--variant unmapped` under the safety-gates feature.
