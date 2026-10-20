---
name: verify-centrum-rozliczen
description: Verify Centrum rozliczeń, MAXIMISEART-Dad's local browser app, end to end in Chromium (Playwright for Python) on a synthetic folder okresów, checking screens, API answers, and effects on disk, with retained screenshots; use after changes to the Centrum server, frontend, contract, or launcher.
---

# Verify Centrum rozliczeń

Centrum rozliczeń is a FastAPI server on `127.0.0.1` that serves the committed
frontend build from `src/rozliczenia/centrum/static/` (ADR 0004). Dad opens it
in his browser. This skill launches the real app on a synthetic fixture, clicks
Dad's path in headless Chromium, and checks every visible result against the
server's answer and the files on disk.

## Launch

Run from the repository root (Windows: `py -3`; macOS/Linux: `.venv/bin/python`):

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\run_centrum_verification.py
```

`--feature ustawienia`, `--feature tablica-okresow`, `--feature uklad-folderow-taty`, `--feature konfiguracja`,
`--feature metryki`, `--feature przygotowanie-pliku-zbiorczego`,
`--feature przebieg-rozliczen`, `--feature diagnoza`, or `--feature start-i-zamykanie` drives one
feature; the default `all` drives every feature in `features/README.md`, ending
with `start-i-zamykanie`, which closes Centrum through its own button. In `all`,
Dad's whole week runs in order: Przygotowanie pliku zbiorczego, Gotowość, and
Przebieg rozliczeń up to the Status okresu `Rozliczenia pracowników gotowe`;
`przebieg-rozliczen` alone drives Przygotowanie first. Success prints
`VERIFY OK | features=… | evidence=… | scratch_removed=true`; anything else is a
failure, reported as `VERIFY FAIL | …`.

The runner creates `.verification/runs/centrum-<id>` with
`scripts/create_centrum_fixture.py`, then starts `scripts/serve_centrum.py` on a
free port. Readiness is `<root>/server.json` (written only after the port is
bound) plus a `200` from `/api/health`. Teardown is the runner's `finally`: it
terminates the process it started and runs cleanup.

Preconditions, checked by the runner before launching:

- the built frontend exists (`src/rozliczenia/centrum/static/index.html`); after
  frontend changes run `npm ci` and `npm run build` in `frontend/` first, or the
  run proves the old build;
- Playwright for Python and Chromium are installed:
  `py -3 -m pip install -e ".[dev]"` then `py -3 -m playwright install chromium`.

`serve_centrum.py` runs the production app (`create_app` and `serve`), not a
test double. Its inputs are run-local: the settings file and both metrics files
live in the run root, and the platform adapter (Dad's computer) is scripted. A native picker answers
with the path in `<root>/picker/answer.txt` (no file means Dad cancelled) and
logs its title to `<root>/dialogs.jsonl`. Opening a file in Excel or a folder in
Explorer appends the path to `<root>/opened.jsonl` instead of launching an
application. While `<root>/pacing/szablony-ms.txt` exists, each Szablon
pracownika of a Przebieg rozliczeń RUN waits that many milliseconds, so the
live progress and the refused closing can be observed; the drive turns it on
for one RUN only. The adapter is the production boundary for those actions; the real
Windows and macOS adapters are covered by `tests/test_centrum_launcher.py` (real
process, real browser opening) and by hand.

Instances are isolated by port and run root, so two runs can proceed side by
side. Drive only a Centrum this run started. Dad's own Centrum (port `47811`,
`config/centrum-ustawienia.yaml`) is never touched.

## Doctor

The runner runs the doctor before driving and keeps the result in `doctor.txt`.
To check an instance by hand:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\centrum_doctor.py --root "$runRoot"
```

`DOCTOR OK` means `server.json` exists, the URL is on `127.0.0.1`, `/api/health`
returns Centrum's identity and the `pyproject.toml` version, `/` serves the
built frontend, and the settings and metrics files belong to this run. The doctor only reads.

## Drive

`scripts/drive_centrum.py` is the harness, with each feature's steps in `scripts/drive/<feature>.py`: Playwright for Python, sync API,
Chromium at 1440×1000, locale `pl-PL`. It finds elements by ARIA role and
accessible name, the same Polish names Dad reads: buttons such as
`Wskaż folder okresów`, `Zmień Rejestr zleceń`, `Włącz motyw jasny`, and
`Plik zbiorczy, okres 29_05_10_2026`; the table `Tablica okresów`; the region
`Następny krok`; the groups `Rejestr zleceń` and `Folder okresów`; on
Konfiguracja the groups named after each Wzorzec and the list `Wykonawcy`. The recipes
and their exact handles are in the feature files. To drive one feature against
a running instance:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\drive_centrum.py --root "$runRoot" --url "$url" --evidence "$evidenceRoot" --feature tablica-okresow
```

## Evidence

Evidence lives in `.verification/evidence/centrum-<id>/` and survives cleanup:

- `fixture.txt`, `server.txt` (server console), `doctor.txt`, `drive.txt`
  (every step and check), `cleanup.txt`, `self-test.txt`;
- `screenshots/NN-<step>.png` and `aria/NN-<step>.txt` for each step, captured
  after transitions finish; on failure, also `screenshots/zz-failure.png`;
- `api/*.json` with the server's answers, including the refused foreign
  `Origin` and `Host` requests, and `api/start-*.txt` with the real launcher's
  console output;
- `state/` with `opened.jsonl`, `dialogs.jsonl`, the settings file, and the
  Centrum log (`centrum-rozliczen.log`) as the run left them.

Proof standards:

- Drive Dad's path through the UI. A screen state alone is not proof: pair it
  with the API answer and the side effect (settings file, picker log, opened
  path).
- Treat the scripted platform adapter as the only stand-in for Dad's computer.
  Two harness steps are labelled in `drive.txt`: Gotowość, where the drive
  edits the Plik zbiorczy instead of Excel, and the Szablony pacing.
- Look at the screenshots after a UI change; a passing run does not judge
  visual quality.
- Evidence holds synthetic paths only. The self-test fails if the fixture's
  workbook row marker reaches evidence, which would mean Centrum read workbook
  content.

## Cleanup

The runner calls `scripts/centrum_cleanup.py` in `finally`. It stops the server
recorded in `server.json` only if that URL still answers as Centrum, then
removes the run root. It never touches evidence and never kills by process
name. After a runner that was itself killed:

```powershell
py -3 .agents\skills\verify-centrum-rozliczen\scripts\centrum_cleanup.py --root "$runRoot"
```

Then confirm the evidence directory still exists.

## Helpers

- `scripts/run_centrum_verification.py`: the one-command orchestrator (above).
- `scripts/create_centrum_fixture.py --root "$runRoot"`: synthetic folder
  okresów `INEA` (one period per Status okresu, one Plik zbiorczy with a
  Wykonawca missing from the konfiguracja wykonawców, plus a non-period folder),
  synthetic Rejestr zleceń, a `config/` with a synthetic konfiguracja
  wykonawców and the three Wzorce, both metrics files with a synthetic history,
  `fixture.json` with "today" `2026-10-19`, the expected Tablica okresów, the
  expected Wykonawcy, and the metrics facts the drive checks.
- `scripts/serve_centrum.py --root "$runRoot" --port 47900`: serves Centrum for
  the run.
- `scripts/centrum_doctor.py --root "$runRoot"`: the read-only doctor.
- `scripts/drive_centrum.py --root "$runRoot" --url "$url" --evidence "$evidenceRoot"`:
  the Playwright drive.
- `scripts/centrum_cleanup.py --root "$runRoot"`: stop and remove one run.
- `scripts/centrum_self_test.py --evidence-root "$evidenceRoot"`: skill package
  and evidence hygiene check.

Read `features/README.md` before choosing a feature. Each Centrum slice adds
its feature file and drive steps in the same PR as the feature; keep the map
honest with `/maintain-verification-skill`.
