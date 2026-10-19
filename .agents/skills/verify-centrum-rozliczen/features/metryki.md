# Metryki

Metryki show the history of every Uruchomienie procesu of both processes,
including those started from the `.cmd` launchers, read from the CLI's two
metrics files on every request: P50/P95 per process and mode from five
completed observations, the result distribution, a stage-times chart, the
interrupted runs with their phase times, and a sortable, filterable history
table. Okresy shows three key numbers above the Tablica okresów. Records the
CLI's reader skips are skipped here too, and no metrics files mean an empty
state, not an error.

## Sub-features

- `metryki-karty-okresow`: Okresy shows the last prepared period, the last Uruchomienie procesu with its result, and the results of the last 8 weeks, matching `/api/periods` and `/api/metrics`.
- `metryki-p50-p95`: the `Statystyki` strip shows the server's P50/P95 and result counts for Przygotowanie RUN.
- `metryki-wykres`: the stage-times chart stacks the four phases of each Przygotowanie RUN, with a legend.
- `metryki-tabela-etapow`: the `Tabela` tab lists each run's phase times with P50/P95 rows per phase.
- `metryki-za-malo-obserwacji`: below five completed observations (Przygotowanie DRY-RUN), P50/P95 show `–` and `od 5 ukończonych (jest N)`.
- `metryki-przerwane`: an interrupted run shows its phase times until the interruption.
- `metryki-historia`: the history lists both processes newest first, marks DRY-RUN with the eye icon and launcher runs with `.cmd`, sorts by `Czas`, filters by process, and shows older runs on demand.
- `metryki-nowy-rekord-z-cli`: a record the real CLI (`run_preparation.py`) appends appears after a reload, without restarting Centrum.
- `metryki-pusty-stan`: with no metrics files the API returns an empty list and the page shows `Jeszcze nie ma metryk`.

## How to get to it (user POV)

- Sidebar `Metryki` (`#/metryki`).
- Sidebar `Okresy` (`#/okresy`): the `Najważniejsze liczby` strip between `Następny krok` and `Tablica okresów`, once the folder okresów is set.
- Returning to the tab or reloading it reads the metrics files again.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`; the doctor also confirms the server reads this run's metrics files (`<root>/metrics/`), not Dad's history next to the tool. If the folder okresów is not set yet, the drive sets it through `Wskaż folder okresów` (see `ustawienia.md`).
- `fixture.json` → `metrics` names both files, the number of valid records (`runs`), the oldest record, and the interrupted run's period and measured phase times. The Przygotowanie file also holds a record with Przebieg rozliczeń counters, and the Przebieg file ends with a torn line; both must be skipped.
- The browser context uses the time zone `Europe/Warsaw`, so dates read as on Dad's computer (`06.10.2026, 08:21` for `06:21Z`).

- **Karty na Okresach.** Open `#/okresy`. `GET /api/metrics` (`api/metryki.json`) has `fixture.metrics.runs` runs of both processes. Group `Najważniejsze liczby` → group `Ostatni przygotowany okres` shows the newest token with `collective_file_exists` from `/api/periods`; group `Ostatnie uruchomienie` shows `OK` and `<process_label> · <date>` of `runs[0]`; group `Ostatnie 8 tygodni` shows `<ok> OK` and `<needs_review> do sprawdzenia · <critical> zatrzymane` from `recent`.
- **P50/P95.** Click link `Metryki`. Group `Statystyki` → groups `P50`, `P95`, `Wyniki` show the server's `statistics` for (`preparation`, `RUN`), durations as tenths of a second rounded half up (`7250` → `7,3 s`).
- **Wykres.** Figure `Wykres czasów etapów` has one `.recharts-bar-rectangle` per non-zero phase of each shown run (up to 12) and the legend `Sprawdzanie`, `Odczyt danych`, `Planowanie`, `Zapisywanie`.
- **Tabela.** Click tab `Tabela`. Table `Czasy etapów` has a header, one row per shown run, and rows `P50`/`P95` whose cells match `percentiles` and `percentiles.phases`.
- **Za mało obserwacji.** In group `Tryb` click `DRY-RUN`. Group `P50` shows `od 5 ukończonych (jest 3)`; the API has `percentiles: null` and `completed_runs: 3`.
- **Przerwane.** Region `Przerwane` contains the interrupted period and `Sprawdzanie 0,4 s · Odczyt danych 1,3 s` plus `do przerwania 1,7 s`.
- **Historia.** Table `Historia Uruchomień procesu` shows 10 rows, newest first; the screen-reader text `DRY-RUN` appears once per DRY-RUN row and `.cmd` once per row. Click button `Czas`: the longest run is first and the column header has `aria-sort="descending"`. In group `Proces w historii` click `Przebieg`: only `Przebieg rozliczeń` rows. Click `Wszystkie`, then `Pokaż starsze`: up to 20 rows.
- **Nowy rekord z CLI.** Run `run_preparation.py --register <root>/brak-rejestru.xlsx --periods-directory <INEA> --period 06_12_10_2026 --dry-run --metrics <fixture.metrics.preparation>`; it exits `1` (no Rejestr zleceń) after appending a `BLAD_KRYTYCZNY` record. `/api/metrics` (`api/metryki-po-cli.json`) has one more run; after a reload the first history row shows `06_12_10_2026`, `Zatrzymano` and `.cmd`.
- **Pusty stan.** Rename both metrics files; `/api/metrics` returns `runs: []` (`api/metryki-brak-plikow.json`) and the page shows `Jeszcze nie ma metryk`. The drive renames them back.
- **Proof.** Screenshots `20`–`27`, `api/metryki*.json`.

## Gotchas

- Statistics are per process and mode. A `BLAD_KRYTYCZNY` record is not a completed observation, but `WYMAGA_SPRAWDZENIA` is.
- The header filter (`Proces`, `Tryb`) drives the strip and the chart only; the history card has its own filters (`Proces w historii`, `Tryb w historii`). Filter and sort state is lost on reload.
- Every fixture run is marked `.cmd`: the metrics schema has no origin field, so Centrum takes `origin` from its own `centrum-uruchomienia.jsonl`, and Metryki runs before any feature that starts an Uruchomienie procesu from Centrum. Runs Centrum started carry `origin: centrum` and no badge, so `--feature metryki` on a run root where they already ran fails the `.cmd` count.
- The CLI step writes a record with the real current time, so it is the newest run; it uses the run-local metrics file, never the tool's.
- Bars render without animation; a capture right after a filter click is still stable.
