# Powiadomienie o naprawie

When Maks closes a Zgłoszenie that Dad sent from the version of the tool that
still runs, Okresy shows the calm notice `Maks naprawił zgłoszony problem.` with the
button `Zaktualizuj narzędzie`. Centrum asks the skrzynka Zgłoszeń about open sent
Zgłoszenia at its first read after start and on entering Okresy, at most once
per 10 minutes; no network passes silently with the last known state. After
Dad updates the tool, the commit differs and the notice is gone by itself. The
button's update itself is driven in `aktualizacja.md`; here the tool's commit is
pinned instead.

## Sub-features

- `naprawa-czeka`: Dad updates the tool and sends the Zgłoszenie of the other problem (the missing Plik zbiorczy Wzorzec) from it, so the closed Zgłoszenie 1 of `zgloszenie`, sent from the older tool, does not count; entering Okresy asks the skrzynka once; the Zgłoszenie is open, so `GET /api/reports/repair` is `{"repaired": false}` and there is no notice; a second read within 10 minutes asks nothing.
- `naprawa-brak-sieci`: after Maks closes the Zgłoszenie in the skrzynka, Okresy within 10 minutes shows the last known state without asking; 10 minutes later without network it asks, gets nothing, and shows no notice and no alert.
- `naprawa-powiadomienie`: with network again, 10 minutes later the status `Maks naprawił zgłoszony problem.` with an enabled `Zaktualizuj narzędzie` is on Okresy; `config/zgloszenia-wyslane.json` keeps `state` `closed`.
- `naprawa-po-aktualizacji`: with another tool commit (Dad updated the tool) the notice is gone and the closed Zgłoszenie is not asked about again.

## How to get to it (user POV)

- Okresy (the start page): the notice sits under the page title, above the board, only while it applies.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK` by `serve_centrum.py`, with the file skrzynka `<root>/skrzynka-zgloszen/`, its question log `<root>/skrzynka-zgloszen-zapytania.jsonl`, the clock shift `<root>/zegar/przesuniecie-min.txt`, and the tool commit override `<root>/github/tool-commit.txt`. The drive needs a Zgłoszenie in `config/zgloszenia-wyslane.json`; run alone, it drives `zgloszenie` first. It writes the synthetic key to `config/zgloszenia-klucz.txt` and removes it at the end.

- **Czeka.** Write 40 × `d` to `<root>/github/tool-commit.txt` and `main-commit.txt` (Dad updated the tool), stop the Przygotowanie without the Wzorzec pliku zbiorczego, click `Diagnoza` and `Wyślij do Maksa`: a new `open` file in the skrzynka, last in `config/zgloszenia-wyslane.json`. Shift the clock by 10 minutes, `page.goto(<url>#/okresy)` and reload, wait for heading `Okresy` and network idle. The question log has one more line; `api/naprawa-czeka.json` is `{"repaired": false}`; no `status` with the notice text.
- **Brak sieci.** Set `state` `closed` in `<root>/skrzynka-zgloszen/<n>.json` (Maks closes it). Re-enter Okresy: no new question, no notice. Create `<root>/skrzynka-zgloszen/brak-sieci`, shift the clock by 10 minutes, re-enter: one new question, no notice, no `alert`, the local state still `open`.
- **Powiadomienie.** Delete `brak-sieci`, shift by 10 minutes, re-enter: `status` `Maks naprawił zgłoszony problem.` holding button `Zaktualizuj narzędzie` (exact, enabled); `api/naprawa-powiadomienie.json` is `{"repaired": true}`.
- **Po aktualizacji.** Write 40 × `e` to `<root>/github/tool-commit.txt` and `main-commit.txt`, re-enter: no notice, `{"repaired": false}`, no new question.
- **Proof.** Screenshots `72`–`75`, `api/naprawa-*.json`, and the checks in `drive.txt`.

## Gotchas

- Every `GET /api/reports/repair`, from the tab or from `run.api`, may ask the skrzynka; count questions in the log, not requests.
- The tab also re-reads the notice on focus and visibility changes; the 10-minute limit keeps these from asking again.
- `tool-commit.txt` and `main-commit.txt` stay after the drive, as after a real update: later features run on the „updated” tool, so the notice stays gone.
- Never point the app at the real GitHub skrzynka; the key is synthetic.
