# Progress and telemetry

Every Uruchomienie procesu reports phase progress, its result, and safe local
timing history; Przebieg rozliczeń also reports Szablony pracowników written
and empty (Przygotowanie pliku zbiorczego: `prepare-collective-file.md`). The machine
script prints the last progress in the shape of the Centrum contract and
returns an exit code that follows the result.

## Sub-features

- `progress-phases` reports `Sprawdzanie`, `Odczyt danych`, `Planowanie`, and `Zapisywanie` in order.
- `progress-templates` reaches 3 of 3 Szablony pracowników, two written and one empty.
- `progress-status` distinguishes Wymaga sprawdzenia (exit `2`) from Zatrzymanie (exit `1`).
- `metrics-safe` appends local JSONL telemetry without customer row contents or source paths.

## How to get to it (user POV)

- Dad sees progress and metrics in Centrum rozliczeń (`verify-centrum-rozliczen`).
- `py -3 tools\uruchom_proces.py` runs are for verification with explicit source and metrics paths.

## Driving it with PowerShell and the machine script

Preconditions:

- Run the one-command orchestrator from the repository root.

- **Check ordered phases and template progress.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. `assert-run.txt` reports `progress_reported=true`: `result.progress.phases` in `run.json` lists `Sprawdzanie`, `Odczyt danych`, `Planowanie`, `Zapisywanie` in that order, each `completed`; `templates_completed` is 3 of `template_total` 3; the figures are `Wiersze danych` 3, `Zapisane szablony` 2, `Puste szablony` 1, `Problemy` 0; and `result` is `OK`.
- **Check the exit code.** The default fixture records exit `0` and result `OK`. The `unmapped` variant returns `2` (`WYMAGA_SPRAWDZENIA`) for dry-run and `1` (`BLAD_KRYTYCZNY`, stop `NIEZNANY_WYKONAWCA`) for the real run, which stops before publication.
- **Check metrics.** `assert-run.txt` reports `metrics_safe=true`: the history holds a completed `DRY-RUN` then `RUN` record, both `OK`, with no row content or scratch path. Each record has `schema_version`, `started_at`, `mode`, `period`, `completed`, `result`, `phase_durations_ms`, `total_duration_ms`, and `counters`; the copies stay in the evidence as `dry-run-metrics.jsonl` and `run-metrics.jsonl`. Every JSON result also reports `metrics_saved: true`.
- **Check repeated-run statistics.** P50 and P95 per process and mode appear in Centrum's Metryki once five completed records exist; prove them with `verify-centrum-rozliczen --feature metryki`.

## Gotchas

- An unmapped worker is a dry-run warning and a critical real-run failure; other workbooks are never published without a complete mapping.
- Metrics are observability only; failure to append them must not be mistaken for a settlement failure.
- Never capture workbook row contents or customer-identifying paths in evidence.
