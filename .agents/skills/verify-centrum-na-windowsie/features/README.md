# Centrum rozliczeń na Windowsie: verification map

This directory is the maintained source for verifying what Dad does with Centrum on his Windows computer outside
the tab: install it, start it from the desktop, answer Windows' own windows, and update it. Read this index before
driving, then use the matching feature file as the recipe. Screens inside the tab belong to
`verify-centrum-rozliczen`; add a feature here only when Windows itself is part of the behaviour.

## Baseline preconditions

- A Windows machine with nothing on port `47811` and a Python that has `pythonw.exe` beside it (GitHub's
  `windows-latest` with `actions/setup-python` in the workflow).
- `run_windows_verification.py` created a fresh run root with `windows_tool.prepare`: `dane/` (folder okresów `INEA`
  with `29_05_10_2026`, `22_28_09_2026`, `15_21_09_2026`, `06_12_10_2026` and `Archiwum`; Rejestr zleceń
  `ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`; Dad's `config/` with the konfiguracja wykonawców and three Wzorce),
  the origin `origin.git` with `main` on `first`, and `windows.json`.
- The drive's environment carries `windows_tool.boundaries` (browser recorder, GitHub address rewritten to the
  origin); Centrum inherits it through the shortcut.
- No settings file exists before `wskazanie-folderow`.

## Driving conventions

- Start Centrum only with the run's shortcut (`windows_desktop.start_shortcut`), never with `python run_centrum.py`.
- Find native windows by class and exact title, and require that Centrum's own process (the port owner) owns a
  picker; never click by coordinates.
- Find tab elements by ARIA role and exact Polish accessible name, as in `verify-centrum-rozliczen`.
- Change GitHub's newest Wydanie only with `windows_tool.release`, and put it back to `newest` when a feature ends.

## Proof and skip reporting

- Every step records the action, the tab (`screenshots/`) or the desktop (`pulpit/`), and the effect: process facts,
  the Centrum log, Dad's settings, the clone.
- Report a feature as verified only when the verdict lists it under `features=`; `przygotowanie=` is not proof of a
  feature, and a feature left out is a skip.
- `VERIFY FAIL` keeps `zz-failure.png` of the tab and the desktop and every step before the failure.
- Evidence holds synthetic paths only.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the user-visible behaviour, then exactly these H2s in
order: `Sub-features` (IDs matching `STEP <feature> | <id>` in `drive.txt`), `How to get to it (user POV)`,
`Driving it with the Windows harness` (starting with `Preconditions:`), and `Gotchas`. A new feature adds its file
here, its module in `scripts/windows_drive/`, its entry in `windows_drive.FEATURES` and `PREREQUISITES` and in
`run_windows_verification._drive`, in the same PR.

## Features

- [Instalacja](./instalacja.md) covers Maks's installation on Dad's computer: the clone on `main` in a user folder with a space and a Polish letter, Dad's own `config/` files that leave the clone clean, `py -3 -m pip install -r requirements.txt`, and `install_centrum_shortcut.py` creating `Centrum rozliczeń.lnk` that starts the same Python's `pythonw.exe` with the tool's `run_centrum.py` and Centrum's icon.
- [Komunikat startu](./komunikat-startu.md) covers a double click while another program holds Dad's port: Windows' own message box `Centrum rozliczeń` from the shortcut's `pythonw.exe` with the exact three-part Komunikat, no console, the process ending when Dad closes it, and `blad-startu` in the Centrum log.
- [Start skrótem](./start-skrotem.md) covers the double click on the shortcut: Centrum on port `47811` as the tool's `pythonw.exe` with no window and no console host, the tab opened in Dad's browser, `health` on the tool's commit, the first-start screen and the version on Konfiguracja, and a second double click that only opens the tab again (`juz-dziala`, one Centrum, no window).
- [Wskazanie folderów](./wskazanie-folderow.md) covers Windows' own pickers that Centrum's process opens: the folder okresów and the Rejestr zleceń typed and confirmed as Dad does, the Tablica okresów and the Rejestr in the tab, both paths in Dad's settings file, and a period folder opened in a real Explorer window.
- [Aktualizacja narzędzia](./aktualizacja.md) covers the update from Konfiguracja on Windows: Git for Windows moving the clone, pip installing the new requirements under `pythonw.exe`, the old Centrum closing, the detached restart guardian starting the new version without a console and the tab reloading with `Zaktualizowano`, and a new version that does not start rolled back to the old one with `Nowa wersja narzędzia nie wystartowała.`, both leaving Dad's `config/` byte for byte and no guardian behind.
