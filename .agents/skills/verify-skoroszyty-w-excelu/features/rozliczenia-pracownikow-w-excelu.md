# Rozliczenia pracowników w Excelu

After Przebieg rozliczeń ran on the Plik zbiorczy Dad saved in Excel, he opens
each Rozliczenie pracownika in the Folder rozliczeń pracowników. Each opens with
no dialog, links to the same Słownik as the Wzorzec rozliczenia pracownika, and
shows exactly its Wykonawca's Zlecenia skuteczne with what he typed, the
Wzorzec's formulas calculating the amounts, and the Rejestr's Wyróżnienia.

## Sub-features

- `bez-okna`: each of the three Rozliczenia pracowników opens in Excel with no dialog.
- `wiersze-a-at`: the Wiersze danych are the Wykonawca's Zlecenia skuteczne in Plik zbiorczy order, and each row's `A:AT` in Excel equals that row of the Plik zbiorczy after Gotowość.
- `hiperlacza`: each Wiersz danych has in the file Przebieg wrote the `A:AT` Hiperłącza of its row in the Plik zbiorczy Excel saved.
- `formuly`: every Wiersz danych has the R1C1 formulas of `AU18:AY18` of the Wzorzec rozliczenia pracownika, `AU:AX` shows no error, and the rows Dad filled show a positive amount in `AU`.
- `wyroznienia`: Adrian Testowy's `PREP-SYN-ZL-2` keeps the yellow ADRES with bold dark red text, Kamil Syntetyczny's `PREP-SYN-ZL-4` the italic WYKONAWCA; Darek Fikcyjny has none (`cells=0`).

## How to get to it (user POV)

- Centrum rozliczeń, Tablica okresów, the period with Status okresu `Rozliczenia pracowników gotowe`: the Folder rozliczeń pracowników link, then a double click on a file.
- Finder: `INEA\<okres>\Rozliczenie pracowników <okres>\Rozliczenie <okres> - <Wykonawca>.xlsx`.

## Driving it with AppleScript

Preconditions: `gotowosc-w-excelu` passed and Przebieg rozliczeń ended `OK` with `Zapisane szablony` 3 (`przebieg.json`).

- **Open.** For Adrian Testowy, Darek Fikcyjny, Kamil Syntetyczny: copy the file to the desk, `excel.open_file`. `STEP … bez-okna | <Wykonawca> | open_seconds=…`.
- **Link.** `excel.link_names` equals the Wzorzec rozliczenia pracownika's list.
- **Rows.** `NUMER ZL.` from row 18 gives exactly `-2, -7` (Adrian), `-6` (Darek), `-4` (Kamil). Each row's `excel.read("A:AT")` equals the remembered Plik zbiorczy row cell by cell; a difference names the columns.
- **Hiperłącza.** openpyxl reads `A:AT` hyperlinks of each row in the Folder okresu's file; they equal those `gotowosc-w-excelu` read from Excel's save.
- **Formulas.** As in `otwarcie-plikow-okresu`, against the worker Wzorzec's reference; `AU` above zero in the filled rows.
- **Wyróżnienia.** `excel.fill` as in `otwarcie-plikow-okresu`, for the cells whose order is in this file.
- **Close.** `excel.close` in `finally`, also after a failed check.

## Gotchas

- The Wzorzec rozliczenia pracownika has its own rates in row 14, so its amounts differ from the Plik zbiorczy's; only their presence and the formulas are compared.
- Kamil's row was not filled: its `N:AT` must still equal the Plik zbiorczy's (the Wzorzec's zeros and empty cells), which `wiersze-a-at` covers.
- `wiersze-a-at` compares Excel's reading of both files, so a date shows the same in both; a difference there is a real change of the cell, not of rendering.
