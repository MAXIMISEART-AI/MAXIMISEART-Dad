# Konfiguracja

Before a run, Dad sees on Konfiguracja whether the tool is ready: whether the
three Wzorce are in place and pass the engine's Sprawdzanie, which Wykonawcy
the konfiguracja wykonawców lists, and which version of the tool runs. A
problem is a three-part message (what, where, what to do). The page is read
only: Centrum never changes the konfiguracja wykonawców, a Wzorzec, or an
Excel lock file.

## Sub-features

- `konfiguracja-gotowa`: all three Wzorce show as ready (`3 z 3`), the Wykonawcy match the konfiguracja wykonawców in order, and the version matches `pyproject.toml`.
- `konfiguracja-tylko-do-odczytu`: the `Tylko do odczytu` badge explains itself in a tooltip, and the page offers no action on these files; its only button is `Zaktualizuj narzędzie` (see `aktualizacja.md`).
- `konfiguracja-wzorzec-otwarty`: an Excel lock file next to the Wzorzec pliku zbiorczego shows `Otwarty w Excelu` with the three-part message; after the lock goes away, a return to the tab shows it ready.
- `konfiguracja-brak-wzorca`: a missing Wzorzec rozliczenia pracownika shows `Brak pliku` with the Przebieg rozliczeń's own stop message, which ends by telling Dad to tell the maintainer.
- `konfiguracja-nieczytelna-konfiguracja-wykonawcow`: a broken konfiguracja wykonawców replaces the Wykonawcy with the three-part message.
- `konfiguracja-bez-zmian`: after all reads, the konfiguracja wykonawców and the Wzorce keep their bytes and modification times.

## How to get to it (user POV)

- Sidebar `Konfiguracja` (`#/konfiguracja`). No settings are needed.
- Returning to the Centrum tab, or reloading it, reads the configuration again.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. `serve_centrum.py` points Konfiguracja at `<root>/config`, where `create_centrum_fixture.py` wrote `worker_mapping.yaml` (Wykonawcy `Wykonawca Testowy A`, `B`, `C`) and the three synthetic Wzorce. Dad's real `config/` is never read.

- **Ready.** Open the URL, click link `Konfiguracja` (exact). Heading `Konfiguracja` (level 1) is visible. `GET /api/configuration` (`api/konfiguracja-gotowa.json`) reports the three Wzorce `ready`, the fixture's Wykonawcy in order, and the `pyproject.toml` version. On screen each group `Wzorzec rozliczenia wewnętrznego` / `Wzorzec pliku zbiorczego` / `Wzorzec rozliczenia pracownika` (exact) holds img `Na miejscu i czytelny`, the badge reads `3 z 3`, list `Wykonawcy` has the same items, `Wersja <version>` is shown in the card `Narzędzie`, and there is no `alert`.
- **Read only.** Hover the text `Tylko do odczytu`. Tooltip `Zmiany robi osoba utrzymująca narzędzie.` appears. `main` holds three buttons: the header's menu and theme buttons and `Zaktualizuj narzędzie` in the card `Narzędzie`.
- **Open in Excel.** Create `<root>/config/~$Wzorzec pliku zbiorczego.xlsx`, reload. Group `Wzorzec pliku zbiorczego` shows `Otwarty w Excelu`; the alert `Wzorzec jest otwarty w Excelu.` names the file and folder `config` and says to remove the leftover `~$…` file; the badge reads `2 z 3`; the API answer has `problem` `open_in_excel` (`api/konfiguracja-wzorzec-otwarty.json`). The lock file still exists. Remove it, dispatch `focus`: the group shows `Na miejscu i czytelny` again.
- **Missing Wzorzec.** Rename `Wzorzec rozliczenia pracownika.xlsx` aside, reload. The group shows `Brak pliku`; the alert `Nie można użyć Wzorca rozliczenia pracownika. Nie znaleziono Wzorca rozliczenia pracownika: Wzorzec rozliczenia pracownika.xlsx.` (the Przebieg rozliczeń's stop for this Wzorzec) ends with `W innym wypadku przekaż ten komunikat osobie utrzymującej narzędzie.`; the API has `problem` `missing`. Rename it back.
- **Broken konfiguracja wykonawców.** Rename `worker_mapping.yaml` aside, write invalid YAML in its place, reload. The alert `Konfiguracja wykonawców jest niepoprawna. Plik nie jest poprawnym YAML.` (Przebieg rozliczeń's own stop; Przygotowanie pliku zbiorczego words the same problem differently) names `plik worker_mapping.yaml` and says `Przekaż ten komunikat osobie utrzymującej narzędzie.`; list `Wykonawcy` is gone; the API has `workers.state` `unreadable`. Delete the broken file and rename the original back.
- **No changes.** Reload: all three Wzorce are ready. The snapshot of the four configuration files (bytes and `st_mtime_ns`) equals the one taken before the feature, and no `~$*` file is left.
- **Proof.** Screenshots `10`–`14`, `api/konfiguracja-*.json`, and the `konfiguracja-bez-zmian` check in `drive.txt`.

## Gotchas

- Break files only by renaming or adding them and undo by renaming back. Rewriting a file changes its modification time and makes the `konfiguracja-bez-zmian` check meaningless.
- Centrum remembers each Wzorzec's Sprawdzanie result until the file's size or modification time, or its lock file, changes; a byte-identical copy with the same timestamp would not be re-checked.
- The worker names are synthetic and appear in evidence on purpose. The Wzorce carry the row marker on a second sheet the Sprawdzanie never reads, so a leak of workbook content still fails the self-test.
- `Wzorzec rozliczenia wewnętrznego` and `Wzorzec rozliczenia pracownika` share a prefix; use `exact=True` for the groups.
