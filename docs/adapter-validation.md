# Adapter Validation Gate

The Python test suite covers the settlement engine and `run.py`. Adapter
validation is separate because the `.cmd` launcher and desktop Excel execute
outside the Python test process.

## CMD Gate

On Windows, `tests/test_cmd_launcher.py` invokes `Utwórz rozliczenia.cmd` through
`cmd.exe` with a synthetic workbook, mapping, and Placeholder. It must finish
with exit code `0`, print `Status końcowy: OK`, and publish exactly one workbook
for every configured worker. The test is skipped on non-Windows systems.

## VBA Gate

Run this gate manually before releasing changes to
`deploy/AutomatyzacjaRozliczen.bas` or `AutomatyzacjaRozliczen.xlsm`:

1. Create a fresh synthetic fixture with the source workbook named
   `Rozliczenie 08_14_09_2026 - zbiorcze.xlsx`, its period folder named
   `08_14_09_2026`, a mapping with three workers, and a shared Placeholder.
   Include rows for two mapped workers and leave the third without rows. Run the
   repository's read-only fixture check before driving Excel.
2. Keep `AutomatyzacjaRozliczen.xlsm` and `Utwórz rozliczenia.cmd` in the same
   directory. Import the current `deploy/AutomatyzacjaRozliczen.bas` into the
   workbook if the module is not already current.
3. Open the workbook in desktop Excel, run `UruchomRozliczenia`, and select the
   fixture source workbook in the file picker.
4. Confirm that Excel waits for the process and displays a successful result. A
   critical-error message or a missing launcher message fails the gate.
5. Confirm that Adrian and Darek contain only their synthetic rows, Kamil is
   empty, workbook structure and formulas are preserved, and the shared
   Placeholder remains unchanged.
6. Remove the disposable fixture with the repository's verification cleanup
   helper. Do not use a real customer workbook for this gate.

Record the VBA gate as **not driven** when desktop Excel is unavailable; a
passing Python suite or CMD smoke test does not replace this manual check.
