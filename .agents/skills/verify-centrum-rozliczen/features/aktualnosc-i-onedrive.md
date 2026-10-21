# Aktualność narzędzia i OneDrive

The Diagnoza has two checks that look beyond Dad's files. `Aktualność
narzędzia` compares the tool's commit with `main` on the public GitHub. A newer
`main` is the cause only when no other check found one (Dad clicks
`Zaktualizuj narzędzie` in the explanation and runs again); next to another
cause it is only a quiet proposal under the explanation, with the same button
second after `Uruchom ponownie` (ADR 0009). While the update runs, the button
cannot be clicked again. No network leaves it `not_checked` and never a cause. `Pliki w OneDrive` finds a Rejestr
zleceń, Wzorzec, or period file that OneDrive keeps only in the cloud and tells
Dad to choose „Zawsze zachowuj na tym urządzeniu”. The server computes both;
the browser shows the explanation and the list `Sprawdzono`.

## Sub-features

- `aktualnosc-nowsza-wersja`: with another `main` on the scripted GitHub and no other cause, the explanation reads `Jest nowsza wersja narzędzia.` with `Zaktualizuj narzędzie` as its main action instead of `Uruchom ponownie` (`next_action` `update`) and no separate proposal.
- `aktualnosc-brak-sieci`: without network the explanation is „Nie znalazłem przyczyny na tym komputerze”; `Aktualność narzędzia` reads `Nie sprawdzono: brak połączenia z GitHubem.` with the icon `nie sprawdzono`.
- `onedrive-tylko-w-chmurze`: a Rejestr zleceń only in the cloud is the cause, naming the file and „Zawsze zachowuj na tym urządzeniu”, with `Uruchom ponownie`; the Rejestr zleceń is unchanged.
- `aktualnosc-propozycja`: the Rejestr zleceń only in the cloud and a newer `main` together: the explanation stays the OneDrive one, and note `Propozycja aktualizacji` under it reads `Jest też nowsza wersja narzędzia.` with an outline `Zaktualizuj narzędzie` (`update_proposal` `true`).
- `aktualnosc-aktualizacja-w-trakcie`: a click on that button starts the update; while it runs, the region shows `Pobieranie nowej wersji…`, the button is disabled, and a second click sends nothing; the update ends with `Masz najnowszą wersję.`
- `aktualnosc-i-onedrive-przeszly`: an up-to-date tool and files on the computer pass both checks; the Centrum log has both causes by code.

## How to get to it (user POV)

- Uruchomienia: a stop „do Maksa” (or a repeated stop) offers `Diagnoza` on the `Zatrzymanie` banner; the explanation `Wyjaśnienie Diagnozy`, the note `Propozycja aktualizacji` when there is one, and the collapsed list `Sprawdzono (10)` appear in region `Diagnoza`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK` by `serve_centrum.py`, whose scripted GitHub answers the tool's own commit for `main` (up to date) and whose scripted OneDrive keeps every file on the computer. Run alone, the drive points Centrum to the fixture's folder okresów and Rejestr zleceń itself. The tool is the run's clone `<root>/aktualizacja/klon`, so it has a commit.

- **Zatrzymanie bez przyczyny na komputerze.** On `#/uruchomienia` (after `Nowe Uruchomienie procesu` when a result is shown) choose radio `Przygotowanie pliku zbiorczego` and option `08_14_09_2026 · Brak plików okresu`, rename `config/Wzorzec rozliczenia wewnętrznego.xlsx` aside, click `Podgląd bez zapisu` (exact), wait for `Nie znaleziono wzorca, z którego powstają pliki okresu.` and `stop_kind` `for_maks`, rename the Wzorzec back. Each step below reloads and clicks `Diagnoza` on the banner.
- **Nowsza wersja.** Write 40 × `f` to `<root>/github/main-commit.txt`. `Wyjaśnienie Diagnozy` reads `Jest nowsza wersja narzędzia.` and `Kliknij „Zaktualizuj narzędzie”.` and holds button `Zaktualizuj narzędzie` (exact, enabled, primary) and no `Uruchom ponownie`; there is no note `Propozycja aktualizacji`. `POST /api/runs/{id}/diagnosis` with Centrum's `Origin` (`api/aktualnosc-nowsza-wersja.json`): `Aktualność narzędzia` `failed`, `next_action` `update`, `update_proposal` `false`.
- **Brak sieci.** Delete `main-commit.txt`, create `<root>/github/brak-sieci`. The explanation reads `Nie znalazłem przyczyny na tym komputerze.`; click `Sprawdzono (10)`: item `Aktualność narzędzia` reads `Nie sprawdzono: brak połączenia z GitHubem.` with icon `nie sprawdzono`. The answer has `not_checked` and `next_action` `report`.
- **Tylko w chmurze.** Delete `brak-sieci`, write the Rejestr zleceń's full path to `<root>/onedrive/tylko-w-chmurze.txt`. The explanation reads `Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.`, `plik <Rejestr zleceń name>`, and „Zawsze zachowuj na tym urządzeniu”, with `Uruchom ponownie`. `Pliki w OneDrive` is `failed`; the Rejestr zleceń keeps its bytes and `st_mtime_ns`.
- **Propozycja.** Keep `tylko-w-chmurze.txt` and write 40 × `f` to `main-commit.txt` again. `Wyjaśnienie Diagnozy` still reads `Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.` with `Uruchom ponownie`; under it note `Propozycja aktualizacji` reads `Jest też nowsza wersja narzędzia.` and holds button `Zaktualizuj narzędzie` (enabled, outline). The answer (`api/aktualnosc-propozycja.json`) has the OneDrive explanation, `Aktualność narzędzia` `failed`, `next_action` `rerun`, and `update_proposal` `true`.
- **W trakcie aktualizacji.** Harness: point the local origin's `main` (`tool.origin`) at the clone's `HEAD`, so the update changes nothing, and write `4000` to `<root>/pacing/aktualizacja-ms.txt`. Click `Zaktualizuj narzędzie` in the note: status `Pobieranie nowej wersji…` appears in region `Diagnoza` and the button is disabled; a forced second click sends no `POST /api/tool-update`, and `GET /api/tool-update` is `{"state": "running", "step": "fetching"}`. Screenshot `140` (live). Remove the pacing file (the update read it at its start, so it still waits the 4000 ms): status `Masz najnowszą wersję.` appears, the button is enabled again, and the log has exactly one more `aktualizacja-start`. Harness: the origin's `main` goes back to `tool.newest` (also in `finally`).
- **Oba przeszły.** Delete `main-commit.txt` and `tylko-w-chmurze.txt`. Under `Sprawdzono (10)` item `Aktualność narzędzia` reads `Najnowsza wersja z GitHuba, commit …` and `Pliki w OneDrive` has icon `przeszło`. The Centrum log has `przyczyna=NOWSZA_WERSJA_NARZEDZIA` and `przyczyna=PLIK_TYLKO_W_CHMURZE`.
- **Proof.** Screenshots `76`–`79`, `81` and `140`, `api/aktualnosc-*.json`, `api/onedrive-*.json`, and the checks in `drive.txt`.

## Gotchas

- Never let `serve_centrum.py` use the real GitHub source: the verification must not reach the internet. The real source's time limit is covered by `tests/test_aktualnosc_narzedzia.py` against a silent local server.
- A newer `main` explains the stop only without another cause, so `Nowsza wersja` needs the Wzorzec renamed back first; remove `main-commit.txt` before `Oba przeszły`, or `Aktualność narzędzia` stays `failed` and becomes the explanation.
- Restore the Wzorzec by renaming it back, never by copying: `diagnoza` compares modification times.
- Opening `Sprawdzono (10)` twice collapses it again; open it once per Diagnoza.
- The update in `W trakcie aktualizacji` is real: without the harness pointing the origin's `main` at the clone's `HEAD`, a run of this feature alone would move the clone and restart Centrum. Its result `Masz najnowszą wersję.` stays Centrum's Aktualizacja narzędzia until the next one, so later features see it next to every update button; the scripted GitHub's `main` (`main-commit.txt`) is a separate stand-in, so the explanation can still say there is a newer version.
