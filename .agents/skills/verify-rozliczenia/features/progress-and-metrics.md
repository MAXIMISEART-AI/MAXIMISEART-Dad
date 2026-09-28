# Progress and telemetry

The terminal dashboard gives the user phase progress, per-template results,
semantic status, exit code, and safe local timing history for a settlement run.

## Sub-features

- `progress-phases` reports `Sprawdzanie`, `Odczyt danych`, `Planowanie`, and `Zapisywanie` in order.
- `progress-templates` reaches `3/3 (100%)` and reports per-template statuses.
- `progress-status` distinguishes an operational warning exit (`2`) from a critical failure exit (`1`).
- `metrics-safe` appends local JSONL telemetry without customer row contents or source paths.

## How to get to it (user POV)

- Run `py -3 run.py` from a terminal with a source path and metrics path.
- Run `Utwórz rozliczenia.cmd` from a terminal or by choosing a source in its file dialog.
- Run the Excel button `UruchomRozliczenia`; the same engine output is reflected in the launched process.

## Driving it with PowerShell and run.py

Preconditions:

- Run the one-command orchestrator from the repository root.
- Its UTF-8 evidence files retain plain CLI output; do not rely on a Rich live screen that disappears at process exit.

- **Check ordered phases.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py` and assert the first occurrences in `run.txt` are `Sprawdzanie`, `Odczyt danych`, `Planowanie`, then `Zapisywanie`.
- **Check template progress.** Assert `Postęp szablonów: 3/3 (100%)`, `Liczniki:`, and the per-template status lines in `run.txt`.
- **Check semantic exit.** The default fixture's `run.txt` records application exit `2` and `Status semantyczny: OSTRZEŻENIE`; the orchestrator returns `0` because that result is expected.
- **Check metrics.** Read the copied evidence file `metrics.jsonl` as JSONL. It contains `mode`, `period`, `completed`, `result`, phase durations, and counters; it must not contain a full source path, address, order number, or row text.
- **Check repeated-run statistics.** After five comparable dry-runs, a sixth dry-run prints `Statystyki DRY-RUN`, `P50`, and `P95`. Use a fresh metrics file for this test and retain the output as evidence.

## Gotchas

- Redirected output uses the plain adapter; the Rich dashboard is not stable evidence by itself.
- An unmapped worker makes the completed run semantically incomplete even if other templates were written.
- Metrics are observability only; failure to append them must not be mistaken for a settlement failure.
- Never capture workbook row contents or customer-identifying paths in a transcript.
