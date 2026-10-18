# Rozliczenia verification map

This is the maintained source for verifying the user-facing MAXIMISEART-Dad
processes. The Dad-facing launchers are `Utwórz rozliczenia.cmd` (Przebieg
rozliczeń) and `Przygotuj plik zbiorczy.cmd` (Przygotowanie pliku zbiorczego);
direct CLI runs provide detailed verification evidence. The VBA adapter is legacy and
outside the supported user workflow.

## Baseline preconditions

- Run from the repository root on Windows PowerShell.
- Python 3.11 or newer and `requirements.txt` are installed.
- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`; it creates fresh roots and runs the doctor before driving.
- Drive the supported CMD route with `py -3 -m pytest tests/test_cmd_launcher.py::test_cmd_launcher_runs_przebieg_rozliczen -q`; the test uses a copied runtime and synthetic workbooks.
- Use `--variant existing`, `--variant locked`, or `--variant unmapped` for the corresponding publication and safety-gate proof.
- Use `--variant preparation` for Przygotowanie pliku zbiorczego.
- Use `--variant preparation-real-templates` locally when `config/` holds the real Wzorce; it is outside CI and `--variant all`, and prints `VERIFY SKIP` without them.
- Never use real customer workbooks or a fixture owned by another verification run. The real Wzorce enter only as byte copies inside the run root.

## Driving conventions

- The one-command orchestrator verifies each engine through its CLI (`run.py`, or `run_preparation.py` for `--variant preparation`); the CMD smoke tests separately drive Dad's launchers in an isolated synthetic runtime.
- Read stdout, stderr, and native exit codes from the UTF-8 evidence files it creates.
- Use workbook reads only for post-action assertions; do not call internal engine functions as proof.
- The orchestrator runs `--dry-run` before a real run, checks the complete plan,
  and verifies that it writes metrics but creates no destination folder or
  output workbook. The real run creates and atomically publishes all worker
  workbooks from the Placeholder.
- Keep evidence in `.verification\evidence\`; cleanup may remove only `.verification\runs\`.

## Proof and skip reporting

- A terminal transcript alone is insufficient: pair it with workbook state and metrics.
- Keep row values, Wzorzec cell values, customer addresses, and order numbers out of evidence and metrics. The only paths in evidence are the synthetic scratch paths and, for `preparation-real-templates`, the Wzorce directory on each transcript's `command:` line; metrics carry no path at all.
- The default fixture returns `0`; `--variant unmapped` separately verifies a
  dry-run warning and a failed real run with no published folder.
- The legacy VBA adapter is not a supported user route and is excluded from live coverage unless reactivated.
- `VERIFY SKIP` from `preparation-real-templates` is a skip: report it as one.
- Run cleanup after every failed iteration and confirm the evidence directory still exists.

## Features

- [Workbook preparation](./prepare-workbooks.md) covers Placeholder copies and all-or-nothing publication.
- [Dry-run planning](./dry-run.md) covers safe inspection before writing.
- [Worker settlement](./settle-workbooks.md) covers fan-out into mapped templates and preserved formulas.
- [Safety gates](./safety-gates.md) covers unknown workers, placeholders, existing data, Excel locks, and the stop on an unreadable Plik zbiorczy.
- [Progress and telemetry](./progress-and-metrics.md) covers observable phases, counters, exit semantics, and safe metrics.
- [Przygotowanie pliku zbiorczego](./prepare-collective-file.md) covers the Rejestr zleceń to Rozliczenie wewnętrzne and Plik zbiorczy process, its dry-run, and its launcher.
