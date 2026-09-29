# Workbook preparation

One settlement run creates the complete configured worker roster from the
shared Placeholder, fills current-period rows, and publishes the output folder
only after every workbook is ready.

## Sub-features

- `prepare-roster` creates one named workbook for every configured worker.
- `prepare-copy` preserves Placeholder sheets, formulas, rates, formatting, and external links.
- `prepare-empty` creates an empty workbook for a configured worker without source rows.
- `prepare-atomic` stages the folder and publishes it only after all workbooks succeed.
- `prepare-rollback` removes staging files after a workbook failure; an unknown worker is rejected before staging starts.

## How to get to it (user POV)

- Dad passes the source file to `Utwórz rozliczenia.cmd`; this is the supported user-facing launcher.
- For direct verification, run `py -3 run.py --source <source> --config <mapping> --placeholder <placeholder> --metrics <metrics>` with a synthetic fixture.

## Driving it with PowerShell and run.py

- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py` for the direct CLI proof.
- Run `py -3 -m pytest tests/test_cmd_launcher.py::test_cmd_launcher_runs_przebieg_rozliczen -q` to drive the supported CMD launcher in a copied synthetic runtime.
- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant unmapped` to prove an unknown WYKONAWCA prevents publication.
- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing` to prove an existing output folder is preserved.
- Run the write-failure test listed in `safety-gates.md` to prove staging cleanup and retry.

## Gotchas

- The output folder must be absent at start; existing content is never merged or replaced.
- The shared Placeholder is read-only input and is validated before output is created.
- Temporary workbooks are not published under the final folder name until every configured worker is prepared.
- Dry-run plans the same roster but creates no output folder or workbook.
