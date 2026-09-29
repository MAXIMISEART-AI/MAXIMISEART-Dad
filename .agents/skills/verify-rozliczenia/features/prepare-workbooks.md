# Workbook preparation

One settlement run creates the complete configured worker roster from the
shared Placeholder, fills current-period rows, and publishes the output folder
only after every workbook is ready.

## Sub-features

- `prepare-roster` creates one named workbook for every configured worker.
- `prepare-copy` preserves Placeholder sheets, formulas, rates, formatting, and external links.
- `prepare-empty` creates an empty workbook for a configured worker without source rows.
- `prepare-atomic` stages the folder and publishes it only after all workbooks succeed.
- `prepare-rollback` removes staging files after an unknown worker or workbook failure.

## How to get to it (user POV)

- Run `py -3 run.py --source <source> --config <mapping> --placeholder <placeholder> --metrics <metrics>`.
- Pass the source file to `Utwórz rozliczenia.cmd` or use the VBA button; both call the same engine.

## Driving it with PowerShell and run.py

- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py` for a successful synthetic end-to-end run.
- Run the same command with `--variant unmapped` to prove an unknown WYKONAWCA prevents publication.
- Run it with `--variant existing` to prove an existing output folder is preserved.
- Run the write-failure test listed in `safety-gates.md` to prove staging cleanup and retry.

## Gotchas

- The output folder must be absent at start; existing content is never merged or replaced.
- The shared Placeholder is read-only input and is validated before output is created.
- Temporary workbooks are not published under the final folder name until every configured worker is prepared.
- Dry-run plans the same roster but creates no output folder or workbook.
