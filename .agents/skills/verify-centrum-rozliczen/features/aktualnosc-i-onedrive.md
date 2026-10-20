# Aktualność narzędzia i OneDrive

The Diagnoza has two checks that look beyond Dad's files. `Aktualność
narzędzia` compares the tool's commit with `main` on the public GitHub: a newer
`main` is the cause (Dad updates the tool and runs again), while no network
leaves it `not_checked` and never a cause. `Pliki w OneDrive` finds a Rejestr
zleceń, Wzorzec, or period file that OneDrive keeps only in the cloud and tells
Dad to choose „Zawsze zachowuj na tym urządzeniu”. The server computes both;
the browser shows the explanation and the list `Sprawdzono`.

## Sub-features

- `aktualnosc-nowsza-wersja`: with another `main` on the scripted GitHub, the explanation reads `Jest nowsza wersja narzędzia.` with `Uruchom ponownie` (`next_action` `rerun`).
- `aktualnosc-brak-sieci`: without network the explanation is „Nie znalazłem przyczyny na tym komputerze”; `Aktualność narzędzia` reads `Nie sprawdzono: brak połączenia z GitHubem.` with the icon `nie sprawdzono`.
- `onedrive-tylko-w-chmurze`: a Rejestr zleceń only in the cloud is the cause, naming the file and „Zawsze zachowuj na tym urządzeniu”, with `Uruchom ponownie`; the Rejestr zleceń is unchanged.
- `aktualnosc-i-onedrive-przeszly`: an up-to-date tool and files on the computer pass both checks; the Centrum log has both causes by code.

## How to get to it (user POV)

- Uruchomienia: a stop „do Maksa” (or a repeated stop) offers `Diagnoza` on the `Zatrzymanie` banner; the explanation `Wyjaśnienie Diagnozy` and the collapsed list `Sprawdzono (10)` appear in region `Diagnoza`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK` by `serve_centrum.py`, whose scripted GitHub answers the tool's own commit for `main` (up to date) and whose scripted OneDrive keeps every file on the computer. Run alone, the drive points Centrum to the fixture's folder okresów and Rejestr zleceń itself. The run root is a git checkout, so the tool has a commit.

- **Zatrzymanie bez przyczyny na komputerze.** On `#/uruchomienia` (after `Nowe Uruchomienie procesu` when a result is shown) choose radio `Przygotowanie pliku zbiorczego` and option `08_14_09_2026 · Brak plików okresu`, rename `config/Wzorzec rozliczenia wewnętrznego.xlsx` aside, click `Podgląd bez zapisu` (exact), wait for `Nie znaleziono wzorca, z którego powstają pliki okresu.` and `stop_kind` `for_maks`, rename the Wzorzec back. Each step below reloads and clicks `Diagnoza` on the banner.
- **Nowsza wersja.** Write 40 × `f` to `<root>/github/main-commit.txt`. `Wyjaśnienie Diagnozy` reads `Jest nowsza wersja narzędzia.` and holds `Uruchom ponownie`. `POST /api/runs/{id}/diagnosis` with Centrum's `Origin` (`api/aktualnosc-nowsza-wersja.json`): `Aktualność narzędzia` `failed`, `next_action` `rerun`.
- **Brak sieci.** Delete `main-commit.txt`, create `<root>/github/brak-sieci`. The explanation reads `Nie znalazłem przyczyny na tym komputerze.`; click `Sprawdzono (10)`: item `Aktualność narzędzia` reads `Nie sprawdzono: brak połączenia z GitHubem.` with icon `nie sprawdzono`. The answer has `not_checked` and `next_action` `report`.
- **Tylko w chmurze.** Delete `brak-sieci`, write the Rejestr zleceń's full path to `<root>/onedrive/tylko-w-chmurze.txt`. The explanation reads `Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.`, `plik <Rejestr zleceń name>`, and „Zawsze zachowuj na tym urządzeniu”, with `Uruchom ponownie`. `Pliki w OneDrive` is `failed`; the Rejestr zleceń keeps its bytes and `st_mtime_ns`.
- **Oba przeszły.** Delete `tylko-w-chmurze.txt`. Under `Sprawdzono (10)` item `Aktualność narzędzia` reads `Najnowsza wersja z GitHuba, commit …` and `Pliki w OneDrive` has icon `przeszło`. The Centrum log has `przyczyna=NOWSZA_WERSJA_NARZEDZIA` and `przyczyna=PLIK_TYLKO_W_CHMURZE`.
- **Proof.** Screenshots `76`–`79`, `api/aktualnosc-*.json`, `api/onedrive-*.json`, and the checks in `drive.txt`.

## Gotchas

- Never let `serve_centrum.py` use the real GitHub source: the verification must not reach the internet. The real source's time limit is covered by `tests/test_aktualnosc_narzedzia.py` against a silent local server.
- `Aktualność narzędzia` is the first check, so a newer `main` wins over any other cause; remove `main-commit.txt` before the OneDrive step.
- Restore the Wzorzec by renaming it back, never by copying: `diagnoza` compares modification times.
- Opening `Sprawdzono (10)` twice collapses it again; open it once per Diagnoza.
