# Aktualizacja narzędzia

On Konfiguracja, the card `Narzędzie` shows the tool's version, its commit,
and whether it is the newest (`Aktualna`, `Jest nowsza wersja`, `Nie
sprawdzono`). Dad clicks `Zaktualizuj narzędzie`: the card shows the step
while Centrum fetches `main` and moves the tool's clone forward. After a
successful update Centrum closes itself, the restart guardian starts the new
version on the same port, and the tab waits, reloads by itself, and briefly
shows `Zaktualizowano`; nothing changed gives `Masz najnowszą wersję.` During
the update a second update and closing Centrum are refused. In this run the tool
is the fixture's synthetic clone with a local "origin", and its Centrum is the
run's scripted Centrum, so the restarted Centrum keeps the run-local
boundaries; the verification never touches the checkout it runs from and never
reaches GitHub.

## Sub-features

- `aktualizacja-jest-nowsza`: with `main` one commit ahead, the card shows the clone's commit and `Jest nowsza wersja`, and no update has run.
- `aktualizacja-postep`: a double click starts one update; the card shows `Pobieranie nowej wersji…` with the button disabled, and a second update and closing Centrum are refused with 409.
- `aktualizacja-ponowny-start`: after the update the old Centrum closes itself (`zamkniecie z=aktualizacja`) and stops answering; the card shows `Ponowne uruchamianie Centrum…` with the button disabled.
- `aktualizacja-zaktualizowano`: without any click the tab reloads on a new Centrum (other `instance`, the new `commit` in `health`) and shows the notification `Zaktualizowano` with the new commit; the card shows the new commit as `Aktualna`, the clone stands on the origin's newest commit, the guardian's result file is gone, the run's `config/` is untouched, and the Centrum log has the start and the end with both commits and no path, the end written by the new Centrum before its `start`.
- `aktualizacja-najnowsza`: a second click says `Masz najnowszą wersję.` and leaves the clone where it is.

## How to get to it (user POV)

- Sidebar `Konfiguracja` (`#/konfiguracja`), card `Narzędzie`, button `Zaktualizuj narzędzie`.
- Diagnoza („Jest nowsza wersja narzędzia”) and the Powiadomienie o naprawie tell Dad to update the tool; the guide points him to Konfiguracja.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. `create_centrum_fixture.py` wrote the tool clone `<root>/aktualizacja/klon` on commit `tool.first` and its "origin" `<root>/aktualizacja/origin.git` whose `main` is `tool.newest` (`fixture.json`). `serve_centrum.py` gives Centrum that clone and origin, so its own commit is the clone's `HEAD`. The clone's `run_centrum.py` (both commits) is a shim that serves this run's scripted Centrum on the port the restart guardian gives it.
- `<root>/github/tool-commit.txt` does not exist (it would pin the tool's commit); in `all` this feature runs right after `konfiguracja`.

- **Newer version.** Harness: write `tool.newest` to `<root>/github/main-commit.txt`, so the scripted GitHub's `main` is the origin's. Open `#/konfiguracja` and reload. Region `Narzędzie` (exact) contains `tool.first[:7]` and `Jest nowsza wersja`; button `Zaktualizuj narzędzie` (exact) is enabled. `GET /api/configuration` (`api/aktualizacja-jest-nowsza.json`) has `commit` `tool.first[:7]` and `freshness` `newer`; `GET /api/tool-update` is `idle`.
- **Progress.** Harness: write `4000` to `<root>/pacing/aktualizacja-ms.txt`, so the update waits before it looks for Git, and `3000` to `<root>/pacing/ponowny-start-ms.txt`, so the restarted Centrum waits before it starts. Record `GET /api/health` (`api/aktualizacja-health-przed.json`), the run's `config/` by content, and a marker on `window`. Double-click the button. Status `Pobieranie nowej wersji…` appears in the card and the button is disabled; `GET /api/tool-update` is `{"state": "running", "step": "fetching"}`. `POST /api/tool-update` and `POST /api/shutdown` with Centrum's `Origin` answer 409 (`api/aktualizacja-druga-odmowa.json`, `api/aktualizacja-zamkniecie-odmowa.json`). The log has exactly one `aktualizacja-start`. Remove the pacing file.
- **Restart.** Status `Ponowne uruchamianie Centrum…` appears in the card (up to 20 s) with the button disabled; `health` does not answer; the log ends with `aktualizacja-start`, `zamkniecie` (`z=aktualizacja`). Capture `100` (live). Remove `ponowny-start-ms.txt`.
- **Updated.** Within 60 s the notification (region `Notifications`, dialog `Zaktualizowano`) shows `tool.newest[:7]` and the `window` marker is gone (the tab reloaded itself); the card shows `tool.newest[:7]` and `Aktualna`, and the button is enabled. `GET /api/health` (`api/aktualizacja-health-po.json`) has `commit` `tool.newest` and another `instance`. `GET /api/tool-update` is `{"state": "updated", "commit": tool.newest[:7]}`; `git rev-parse HEAD` in the clone is `tool.newest`; `GET /api/configuration` has the new commit and `current`; `<root>/config/centrum-aktualizacja.json` is gone and the rest of `config/` is unchanged. The log's update entries are exactly `aktualizacja-start przed=<first>` and `aktualizacja-koniec wynik=ok przed=<first> po=<newest> biblioteki=nie`; after `aktualizacja-start` come `zamkniecie`, `aktualizacja-koniec`, `start` and one `stop` (the old Centrum's, anywhere after `zamkniecie`). Capture `101`.
- **Newest.** Click the button again. Status `Masz najnowszą wersję.`; `GET /api/tool-update` is `up_to_date`; the clone stays on `tool.newest`; the last log entry is `aktualizacja-koniec wynik=AKTUALNA przed=<newest> po=<newest> biblioteki=nie`. Remove `main-commit.txt`.
- **Proof.** Screenshots `93`, `94`, `100`, `101`, `96`, `api/aktualizacja-*.json`, and the checks in `drive.txt`.

## Gotchas

- The progress screenshot is `live`: the spinner turns until the update ends, so waiting for animations would time out.
- `main-commit.txt` must go when the feature ends: later features expect `main` to be the tool's own commit. After the update the clone's `HEAD` is the new commit, so leaving the file would still read as current, but it would mask a feature that pins another `main`.
- The clone is moved by real Git on this machine. Its user configuration applies to the update; the fixture's own commits ignore it.
- The restarted Centrum is a new process started by the restart guardian, not by the runner: `server.txt` holds only the first server's console, the new server rewrites `server.json` with its pid, and cleanup stops that one. In `all`, every later feature drives the restarted Centrum.
- The old Centrum releases the port at once but gives the tab's open event stream up to 5 s before it logs `stop`, so its `stop` may land after the new Centrum's `start`; check the order without it.
- The restart screenshot is `live` and needs the restart pacing: without it the new Centrum answers within about a second.
