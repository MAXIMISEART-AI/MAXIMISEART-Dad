# Aktualizacja narzędzia

On Konfiguracja, the card `Narzędzie` shows the tool's version, its commit,
and whether it is the newest (`Aktualna`, `Jest nowsza wersja`, `Nie
sprawdzono`). Dad clicks `Zaktualizuj narzędzie`: the card shows the step
while Centrum fetches `main` and moves the tool's clone forward, then
`Zaktualizowano. Zamknij Centrum rozliczeń i kliknij skrót.` (he restarts
Centrum himself) or `Masz najnowszą wersję.` when nothing changed. During the
update a second update and closing Centrum are refused. Without internet the
card shows the Komunikat in three parts („brak połączenia z GitHubem”) with
`Wyślij do Maksa` and its preview, the tool stays as it was, and a second click
once the internet is back updates it. In this run the tool is
the fixture's synthetic clone with a local "origin"; the verification never
touches the checkout it runs from and never reaches GitHub.

## Sub-features

- `aktualizacja-jest-nowsza`: with `main` one commit ahead, the card shows the clone's commit and `Jest nowsza wersja`, and no update has run.
- `aktualizacja-brak-sieci`: without internet the click ends in the Komunikat `Nie zaktualizowano narzędzia: brak połączenia z GitHubem.` in three parts, `Zaktualizuj narzędzie` as the main action and `Wyślij do Maksa` beside it; the preview `Co zostanie wysłane` has the code, the commit before and the libraries flag from the log; the clone and Dad's files are unchanged, and the log has the failed update with its code.
- `aktualizacja-postep`: with the internet back, a double click (the retry) starts one update; the card shows `Pobieranie nowej wersji…` with the button disabled, and a second update and closing Centrum are refused with 409.
- `aktualizacja-zaktualizowano`: the card says `Zaktualizowano. Zamknij Centrum rozliczeń i kliknij skrót.`, shows the new commit as `Aktualna`, the clone stands on the origin's newest commit, Dad's files in the clone's `config/` (his changed konfiguracja wykonawców, which the new commit stops tracking, among them) and the run's configuration directory are untouched, and the Centrum log has the start and the end with both commits and no path.
- `aktualizacja-najnowsza`: a second click says `Masz najnowszą wersję.` and leaves the clone where it is.

## How to get to it (user POV)

- Sidebar `Konfiguracja` (`#/konfiguracja`), card `Narzędzie`, button `Zaktualizuj narzędzie`.
- Diagnoza („Jest nowsza wersja narzędzia”) and the Powiadomienie o naprawie tell Dad to update the tool; the guide points him to Konfiguracja.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. `create_centrum_fixture.py` wrote the tool clone `<root>/aktualizacja/klon` on commit `tool.first` and its "origin" `<root>/aktualizacja/origin.git` whose `main` is `tool.newest` (`fixture.json`). The clone's `config/` holds Dad's files `tool.dad_files`: `worker_mapping.yaml`, tracked in `tool.first` and changed locally, which `tool.newest` stops tracking (the first update after #161), and untracked Ustawienia taty, key to Zgłoszenia and a Wzorzec. `serve_centrum.py` gives Centrum that clone and origin, so its own commit is the clone's `HEAD`.
- `<root>/github/tool-commit.txt` does not exist (it would pin the tool's commit); in `all` this feature runs right after `konfiguracja`.

- **Newer version.** Harness: record the bytes of every file in `<root>/config`, and write `tool.newest` to `<root>/github/main-commit.txt`, so the scripted GitHub's `main` is the origin's. `git status` in the clone shows `config/worker_mapping.yaml` changed. Open `#/konfiguracja` and reload. Region `Narzędzie` (exact) contains `tool.first[:7]` and `Jest nowsza wersja`; button `Zaktualizuj narzędzie` (exact) is enabled. `GET /api/configuration` (`api/aktualizacja-jest-nowsza.json`) has `commit` `tool.first[:7]` and `freshness` `newer`; `GET /api/tool-update` is `idle`.
- **No internet.** Harness: move `<root>/aktualizacja/origin.git` out of reach and create `<root>/github/brak-sieci` and `<root>/skrzynka-zgloszen/brak-sieci`. Click `Zaktualizuj narzędzie`. Alert `Ostrzeżenie` in the card contains `Nie zaktualizowano narzędzia: brak połączenia z GitHubem.`, `narzędzie na tym komputerze` and `Narzędzie działa dalej w poprzedniej wersji. Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz.`; `Zaktualizuj narzędzie` is enabled and primary, `Wyślij do Maksa` is outline. `GET /api/tool-update` (`api/aktualizacja-brak-sieci.json`) is `failed` with that message, `next_action` `retry` and `report` `ready`. The clone stays on `tool.first` with `config/worker_mapping.yaml` still changed; the log's update entries are `aktualizacja-start przed=<first>` and `aktualizacja-koniec wynik=BRAK_POLACZENIA przed=<first> po=- biblioteki=nie`. Screenshot `115`. Expand `Co zostanie wysłane`: figure `Treść Zgłoszenia` has the title `BRAK_POLACZENIA: …`, `- Commit przed: <first>`, `- Biblioteki instalowane: nie` and the log entry; the draft has no path. Screenshot `116`. Undo the harness (the internet is back). The drive does not send the Zgłoszenie: `zgloszenie` expects its own to be the skrzynka's first.
- **Progress.** Harness: write `4000` to `<root>/pacing/aktualizacja-ms.txt`, so the update waits before it looks for Git. Double-click the button. Status `Pobieranie nowej wersji…` appears in the card and the button is disabled; `GET /api/tool-update` is `{"state": "running", "step": "fetching"}`. `POST /api/tool-update` and `POST /api/shutdown` with Centrum's `Origin` answer 409 (`api/aktualizacja-druga-odmowa.json`, `api/aktualizacja-zamkniecie-odmowa.json`). The log has exactly one more `aktualizacja-start`. Remove the pacing file.
- **Updated.** Status `Zaktualizowano. Zamknij Centrum rozliczeń i kliknij skrót.` appears; the card shows `tool.newest[:7]` and `Aktualna`, and the button is enabled again. `GET /api/tool-update` is `{"state": "updated", "commit": tool.newest[:7]}`; `git rev-parse HEAD` in the clone is `tool.newest`; every file of `tool.dad_files` has exactly its content, `git ls-files` no longer lists `config/worker_mapping.yaml`, and `<root>/config` has the same bytes as before; `GET /api/configuration` has the new commit and `current`. The log's update entries after the failed one are exactly `aktualizacja-start przed=<first>` and `aktualizacja-koniec wynik=ok przed=<first> po=<newest> biblioteki=nie`.
- **Newest.** Click the button again. Status `Masz najnowszą wersję.`; `GET /api/tool-update` is `up_to_date`; the clone stays on `tool.newest`; the last log entry is `aktualizacja-koniec wynik=AKTUALNA przed=<newest> po=<newest> biblioteki=nie`. Remove `main-commit.txt`.
- **Proof.** Screenshots `93`–`96`, `115`, `116`, `api/aktualizacja-*.json`, and the checks in `drive.txt`.

## Gotchas

- The progress screenshot is `live`: the spinner turns until the update ends, so waiting for animations would time out.
- `main-commit.txt` must go when the feature ends: later features expect `main` to be the tool's own commit. After the update the clone's `HEAD` is the new commit, so leaving the file would still read as current, but it would mask a feature that pins another `main`.
- The clone is moved by real Git on this machine. Its user configuration applies to the update; the fixture's own commits ignore it.
- Centrum does not restart after the update yet: the running server stays on the code it started with. The card's text tells Dad to restart it himself.
