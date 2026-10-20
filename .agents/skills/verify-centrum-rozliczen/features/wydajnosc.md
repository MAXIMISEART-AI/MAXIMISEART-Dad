# Wydajność

Measures how fast Centrum rozliczeń feels on Dad's laptop and compares it with
the baseline in `wydajnosc-baseline.json`: cold start of the four pages, reopening
the tab, two laps through the sidebar with the time a skeleton was shown, the
interactions Dad uses (theme, Metryki filters, the Wykres/Tabela and
Uruchomienie/Historia tabs, collapsing the sidebar, returning to the tab), the
API requests of each scenario, the bundle size, and CPU traces of the cold start
of Okresy and Metryki. It is the hill-climbing loop for frontend changes: every
change that makes Centrum faster or slower updates the baseline in its own PR.
It runs only when named (`--feature wydajnosc`), never in `all`: it takes a few
minutes and needs a quiet CPU.

## Sub-features

- `wydajnosc-rok-pracy`: Centrum points to Dad's year of work (52 periods in his layout, 51 with Rozliczenia pracowników of 14 Wykonawcy, about 260 extra metrics records) through the UI, and the four pages are captured.
- `wydajnosc-pomiar`: every scenario runs in Chromium at CPU 4× (reference) and 6× (pessimistic), five times each by default.
- `wydajnosc-porownanie`: the report gives each scenario's median, baseline and budget per profile and fails when a median exceeds its budget or a scenario's API requests differ from the expected ones.

## How to get to it (user POV)

- Maks, not Dad: `py -3 .agents\skills\verify-centrum-rozliczen\scripts\run_centrum_verification.py --feature wydajnosc` (macOS: `.venv/bin/python …/run_centrum_verification.py --feature wydajnosc`).
- `--baseline <file>` compares with another baseline (e.g. a deliberately broken one); `--powtorzenia <n>` changes the repetitions (fewer for a quick look, never for a baseline).
- The scenarios are Dad's own paths: opening Centrum on a page, clicking through the sidebar, switching the theme, filtering Metryki, switching tabs, collapsing the sidebar, returning to the browser tab.

## Driving it with Playwright for Python

Preconditions:

- The runner creates the fixture with `--wariant rok-pracy`: on top of the usual fixture, `<root>/Rok pracy/Załączniki` holds 52 periods up to `06_12_10_2026` in `Rozliczenia {rok}\{miesiąc}\INEA`, and both metrics files hold 258 more records (Przygotowanie: preview and two RUNs per week; Przebieg rozliczeń: preview and RUN per week before the last). `fixture.json` → `year_of_work` names them.
- The built frontend in `src/rozliczenia/centrum/static/` is the one under test: run `npm run build` in `frontend/` after a frontend change, or the measurement proves the old build.
- Quiet CPU: no other verification, test run, benchmark or browser load on the machine (`pgrep -fl "serve_centrum|chrome-headless|pytest"` shows only this run). A busy machine makes every median slower and the run fails for the wrong reason.
- Profiles follow `docs/agents/komputer-taty.md`: `Emulation.setCPUThrottlingRate` 4× and 6× on a Mac with M4 Max. On another developer computer the multipliers and the baseline do not apply.

- **Rok pracy.** On the drive's tab, answer the picker with `year_of_work.periods_directory` and click `Wskaż folder okresów`, then `Wskaż Rejestr zleceń` with the fixture's register. `/api/periods` (`api/wydajnosc-tablica.json`) holds at least 52 periods, 51 `worker_settlements_ready`; `/api/metrics` (`api/wydajnosc-metryki.json`) has `fixture.metrics.runs` runs. Screenshots `84`–`87` show the four pages on the year. The tab then goes to `about:blank`, so its event stream does not run during the measurement.
- **Ready view.** A view is ready when the `h1` in `[data-slot="sidebar-inset"]` is the page title and no `[data-slot="skeleton"]` or `[aria-busy="true"]` is in the page. A `MutationObserver` from an init script records the time of every change of that state, of every skeleton appearing and disappearing, and of the last DOM change.
- **Scenarios** (each in a fresh context at 1440×1000, `pl-PL`, `Europe/Warsaw`, without HTTP or code cache unless stated):
  - `<strona>/zimny-start`: `#/<strona>` from the first byte to the ready view; details FCP, script time (`Performance.getMetrics`), long tasks.
  - `<strona>/ponowne-otwarcie` (Okresy, Metryki): a new tab in the same context, after two warm-up visits (V8 code cache).
  - `menu/<okrążenie>/<strona>`: from the click on the sidebar link to the ready view, laps Uruchomienia → Metryki → Konfiguracja → Okresy twice after a cold Okresy; `…/szkielet` is the time a skeleton or `aria-busy` was in the page in between.
  - Interactions (`okresy/motyw-jasny`, `okresy/motyw-ciemny`, `metryki/proces-*`, `metryki/tryb-*`, `metryki/zakladka-tabela`, `metryki/zakladka-wykres`, `uruchomienia/zakladka-*`, `menu-boczne/zwin`, `menu-boczne/rozwin`): the longest Event Timing duration of the input (input to next paint, as INP). Below Event Timing's 16 ms threshold the value is 16.
  - `<strona>/powrot-do-karty` (Okresy, Metryki): a `focus` event on the window, until the last API answer or DOM change it caused.
  - CPU traces: one DevTools trace of the cold start of Okresy and Metryki per profile (`wydajnosc/slad-<strona>-<n>x.json`, open in Chrome DevTools → Performance); the report sums the main thread's time per event kind.
- **API requests.** Every `/api/` request of the scenario's context (method and path) is counted per repetition, the event stream and writes included. Every repetition in both profiles must match the baseline's `zapytania_api` exactly; today the cold start of Uruchomienia sends `GET /api/runs/setup` twice. The browser's own measurement (`POST /api/view-timings`, see `pomiar-u-taty.md`) counts too: one per ready view is part of the expected cost, and a second one in a scenario means the view was measured twice.
- **Budget.** `max(baseline × (1 + margines.wzgledny), baseline + margines.minimalny_ms)` per scenario and profile; the bundle (decoded JS and CSS of a cold start) may grow by `margines.bundle_wzgledny`. A scenario missing from the baseline, or a baseline scenario that was not measured, fails too.
- **Report.** `wydajnosc/raport.txt` lists every scenario and profile with median, baseline, budget and verdict (`ok`, `ponad budżet`, `brak w baseline`), the details in brackets, then the API requests per scenario (with the expected ones on a difference), the bundle, the CPU traces, and the failures. `wydajnosc/raport.json` holds the same plus every sample. `drive.txt` repeats the text report. `VERIFY OK` means no failure; `VERIFY FAIL | … drive returned 1` with `DRIVE FAIL | wydajnosc: N porażek` means read the failures at the end of `raport.txt`.
- **Updating the baseline.** Every run writes `wydajnosc/baseline-kandydat.json` in the baseline's format. Update the baseline only in the PR whose change moves the numbers (a frontend change that makes Centrum faster, or a deliberate change in API requests such as one `/api/runs/setup`), and only from a run with the default five repetitions on a quiet CPU: copy the candidate over `wydajnosc-baseline.json`, review `git diff` (only the scenarios the change touches should move beyond the noise; keep `margines` unless the noise itself changed), and put the before/after medians in the PR description. Never update it to make a slower change pass.
- **Proof.** Screenshots `84`–`87`, `api/wydajnosc-*.json`, `wydajnosc/raport.txt`, `wydajnosc/raport.json`, `wydajnosc/baseline-kandydat.json`, `wydajnosc/slad-*.json`.

## Gotchas

- Noise: medians move about ±20 ms at 6× on a quiet machine. A failure by a few milliseconds over budget on a change that does not touch that page is noise or a busy CPU; rerun on a quiet CPU before believing it.
- The measurement takes about five minutes with five repetitions; the runner allows the drive 30 minutes.
- `--powtorzenia 1` is for a quick look or a deliberately broken expectation; one sample is too noisy for a baseline.
- The local server answers in milliseconds; Dad's OneDrive does not. The measurement covers the browser, not OneDrive; server times at Dad's come from the Centrum log.
- The theme interaction switches to light and back; the run starts in dark (no theme saved), so a run root reused after a failure in between may start in light and fail to find `Włącz motyw jasny`.
- Event stream: `GET /api/runs/events` stays open for the page's life and counts as one request of a cold start or reopened tab.
