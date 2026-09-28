# Rozliczenia verification map

This is the maintained source for verifying the user-facing MAXIMISEART-Dad
settlement process. The primary surface is the short-lived terminal CLI;
`Utwórz rozliczenia.cmd` and `deploy/AutomatyzacjaRozliczen.bas` are alternate
launchers for the same Python engine.

## Baseline preconditions

- Run from the repository root on Windows PowerShell.
- Python 3.11 or newer and `requirements.txt` are installed.
- Run `py -3 .cursor\skills\verify-rozliczenia\scripts\run_verification.py`; it creates fresh roots and runs the doctor before driving.
- Use `--variant existing` or `--variant locked` for the corresponding safety-gate proof.
- Never use real customer workbooks or a fixture owned by another verification run.

## Driving conventions

- Drive the user path through the one-command orchestrator; it invokes `py -3 run.py` with synthetic `--source`, `--config`, and `--metrics` paths.
- Read stdout, stderr, and native exit codes from the UTF-8 evidence files it creates.
- Use workbook reads only for post-action assertions; do not call internal engine functions as proof.
- The orchestrator runs `--dry-run` before a real run and verifies that it writes metrics but not workbook input cells.
- Keep evidence in `.verification\evidence\`; cleanup may remove only `.verification\runs\`.

## Proof and skip reporting

- A terminal transcript alone is insufficient: pair it with workbook state and metrics.
- Do not put row values, customer addresses, order numbers, or source paths into evidence transcripts.
- A `2` exit code is expected for the default fixture because the unknown worker is intentional; it is not a successful no-warning run.
- If desktop Excel is unavailable, report the VBA entry point as not driven rather than calling the CLI proof coverage complete for that adapter.
- Run cleanup after every failed iteration and confirm the evidence directory still exists.

## Features

- [Dry-run planning](./dry-run.md) covers safe inspection before writing.
- [Worker settlement](./settle-workbooks.md) covers fan-out into mapped templates and preserved formulas.
- [Safety gates](./safety-gates.md) covers unknown workers, placeholders, existing data, and Excel locks.
- [Progress and telemetry](./progress-and-metrics.md) covers observable phases, counters, exit semantics, and safe metrics.
