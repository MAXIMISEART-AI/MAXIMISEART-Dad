# Adapter Validation Gate

The Python test suite covers the settlement engine and `run.py`. Adapter
validation is separate because the `.cmd` launcher and desktop Excel execute
outside the Python test process.

## CMD Gate

On Windows, `tests/test_cmd_launcher.py` invokes `Utwórz rozliczenia.cmd` through
`cmd.exe` with a synthetic workbook. It must finish with the expected warning
exit code `2`, print `Status końcowy: Wymaga sprawdzenia`, and write only the
two mapped synthetic templates. The test is skipped on non-Windows systems.

## VBA Gate

Run this gate manually before releasing changes to
`deploy/AutomatyzacjaRozliczen.bas` or `AutomatyzacjaRozliczen.xlsm`:

1. Create a fresh synthetic fixture with the source workbook named
   `Rozliczenie 08_14_09_2026 - zbiorcze.xlsx`, its period folder named
   `08_14_09_2026`, and worker templates for Adrian Maciejewski, Darek Nowak,
   Kamil Frontczak, plus the empty placeholder. Include an intentional
   unmapped synthetic worker and run the repository's read-only fixture check
   before driving Excel.
2. Keep `AutomatyzacjaRozliczen.xlsm` and `Utwórz rozliczenia.cmd` in the same
   directory. Import the current `deploy/AutomatyzacjaRozliczen.bas` into the
   workbook if the module is not already current.
3. Open the workbook in desktop Excel, run `UruchomRozliczenia`, and select the
   fixture source workbook in the file picker.
4. Confirm that Excel waits for the process and displays the warning result for
   the fixture's intentional unmapped synthetic worker. A critical-error
   message or a missing launcher message fails the gate.
5. Confirm that Adrian and Darek contain the synthetic input, Kamil and the
   placeholder remain empty, and the `AU` formulas are unchanged. The result
   must match the normal completed run with an intentional warning, not a
   critical error.
6. Remove the disposable fixture with the repository's verification cleanup
   helper. Do not use a real customer workbook for this gate.

Record the VBA gate as **not driven** when desktop Excel is unavailable; a
passing Python suite or CMD smoke test does not replace this manual check.
