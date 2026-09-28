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

1. Create a fresh synthetic fixture as described in
   `.agents/skills/verify-rozliczenia/SKILL.md`; run the doctor first.
2. Keep `AutomatyzacjaRozliczen.xlsm` and `Utwórz rozliczenia.cmd` in the same
   directory. Import the current `deploy/AutomatyzacjaRozliczen.bas` into the
   workbook if the module is not already current.
3. Open the workbook in desktop Excel, run `UruchomRozliczenia`, and select the
   fixture source workbook in the file picker.
4. Confirm that Excel waits for the process and displays the warning result for
   the fixture's intentional unmapped synthetic worker. A critical-error
   message or a missing launcher message fails the gate.
5. Run `assert_results.py --root <fixture-root> --expect run` and require
   `ASSERT OK`. This confirms that the VBA route reached the same workbook
   side effects as the Python and CMD routes.
6. Remove the disposable fixture with the verification cleanup helper. Do not
   use a real customer workbook for this gate.

Record the VBA gate as **not driven** when desktop Excel is unavailable; a
passing Python suite or CMD smoke test does not replace this manual check.
