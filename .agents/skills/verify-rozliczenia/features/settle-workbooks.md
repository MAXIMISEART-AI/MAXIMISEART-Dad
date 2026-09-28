# Worker settlement

Worker settlement copies source values into the matching employee templates,
keeps template formulas, leaves an empty mapped template empty, and reports an
unmapped worker without exposing source row contents.

## Sub-features

- `settle-map` maps source `WYKONAWCA` identifiers to exact template names.
- `settle-copy` writes source values into `A:AT` starting at row 18.
- `settle-preserve` keeps the template `AU` formulas and structure.
- `settle-empty` leaves a mapped worker with no rows as `PUSTY_SZABLON`.

## How to get to it (user POV)

- Run the direct CLI command `py -3 run.py --source <source> --config <mapping> --metrics <metrics>`.
- Pass the source path to `Utwórz rozliczenia.cmd`.
- In desktop Excel, click the button assigned to `UruchomRozliczenia` in `AutomatyzacjaRozliczen.xlsm`.

## Driving it with PowerShell and run.py

Preconditions:

- Run the one-command orchestrator from the repository root.
- Its default fixture contains rows for Adrian Maciejewski and Darek Nowak, no rows for Kamil Frontczak, and one unmapped identifier.

- **Run the real user path.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. Exit code `0` from the orchestrator means both application runs returned their expected semantic exit `2`.
- **Observe progress.** Read `run.txt`; it reaches `Postęp szablonów: 3/3 (100%)`, reports two `ZAPISANO` results and one `PUSTY_SZABLON`, and ends with `Zapisane szablony: 2`.
- **Verify workbook state.** Read `assert-run.txt`; it returns `ASSERT OK` with exit code `0` after checking mapped input values, unchanged `AU18` formulas, an empty Kamil template, and an untouched placeholder.
- **Drive the CMD adapter when needed.** Use a new fixture and run `cmd /c "Utwórz rozliczenia.cmd" "$source"`; use repository mapping names and expect the same engine semantics. Do not use a populated fixture for this second drive.
- **Drive the VBA adapter when needed.** Open `AutomatyzacjaRozliczen.xlsm`, invoke `UruchomRozliczenia`, choose the synthetic source, and inspect the same output files. This is an Excel-only manual path, not a headless assertion.

## Gotchas

- The source file must be named `Rozliczenie 08_14_09_2026 - zbiorcze.xlsx` and live under a folder named `08_14_09_2026`.
- The legacy write-path fixture's placeholder `Rozliczenie 08_14_09_2026 -.xlsx`
  is intentionally ignored. `--dry-run` validates the separate shared
  Placeholder passed with `--placeholder` and previews output names without
  opening existing worker templates.
- The proof must inspect formulas with `data_only=False`; cached formula results are not the template-preservation proof.
- The command may return `2` even when mapped workbooks were safely written; read the semantic summary and workbook state.
