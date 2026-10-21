# Skoroszyty w Excelu verification map

The maintained source for what Dad sees of the processes' files in Excel. Read
this index before driving, then the feature file as the recipe.

## Baseline preconditions

- macOS with Microsoft Excel in `/Applications`, and the app running the agent
  allowed to control Microsoft Excel (Automatyzacja).
- `run_excel_verification.py` built the fixture, `DOCTOR OK` passed, and
  Przygotowanie pliku zbiorczego ended `OK` for `08_14_09_2026`.
- The Rejestr zleceń is `verify-rozliczenia`'s synthetic one: Zlecenia
  skuteczne `PREP-SYN-ZL-2`, `-4`, `-7`, `-6` in Plik zbiorczy order
  (Adrian Testowy twice, Kamil Syntetyczny, Darek Fikcyjny); `-3` is a
  Zlecenie nieskuteczne. Wyróżnienia: ADRES of `-2` yellow with bold dark red
  text, WYKONAWCA of `-4` italic.
- The Wzorce are Dad's (`prawdziwe`) or of his shape (`syntetyczne`): header
  row 17, Wiersze danych from 18, Dad's input in `N:AT`, formulas in `AU:AY`,
  `AY` looking up the Słownik through the one external link.

## Driving conventions

- Excel opens only byte copies on the desk (`SKILL.md`, The desk), through
  `excel.open_file`, which never updates links.
- Find columns by their header in row 17 and rows by `NUMER ZL.`, as the
  processes do; never by a fixed letter outside `N:AY`.
- Compare Excel with Excel: what a Rozliczenie pracownika shows is checked
  against what the Plik zbiorczy showed in the same Excel, and formulas against
  the Wzorzec's R1C1 formulas, so locale and date rendering cancel out.
- Excel calculates itself; a check reads the value Excel shows, never one
  computed by the harness.

## Proof and skip reporting

- A feature is verified only by its `STEP` lines in `drive.txt` of this run.
- `VERIFY SKIP` (no real Wzorce) and a run without `--kontrola-naprawy` leave
  those parts unverified; say so in the report.
- Failure messages and evidence name files, rows, columns and counts, never a
  cell value.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on what Dad sees, then
exactly these H2s in order: `Sub-features` (IDs equal to the `STEP` IDs), `How
to get to it (user POV)`, `Driving it with AppleScript`, `Gotchas`. A new check
gets its sub-feature here and its `run.step` in the runner in the same change.

## Features

- [Otwarcie plików okresu](./otwarcie-plikow-okresu.md) covers the Rozliczenie wewnętrzne and the Plik zbiorczy opening without a dialog, the Plik zbiorczy's external link, its formulas without errors, and its Wyróżnienia.
- [Gotowość w Excelu](./gotowosc-w-excelu.md) covers typing quantities, a charge and remarks into `N:AT` of three Wiersze danych, Excel calculating the amounts, saving and closing without a lock left, and the link surviving Excel's save.
- [Rozliczenia pracowników w Excelu](./rozliczenia-pracownikow-w-excelu.md) covers each Rozliczenie pracownika opening without a dialog after Przebieg rozliczeń read Excel's Plik zbiorczy, its link, its Wiersze danych equal to the Plik zbiorczy in `A:AT`, its formulas and amounts, and its Wyróżnienia.
- [Okno naprawy](./okno-naprawy.md) covers the run stopping on Excel's repair dialog for a workbook with a broken external link; opt-in with `--kontrola-naprawy`, one click.
