# From Rejestr zleceń to Rozliczenia pracowników

Dad's whole weekly path, both processes in turn. Przygotowanie pliku zbiorczego
turns the Rejestr zleceń into the Rozliczenie wewnętrzne and the Plik zbiorczy;
Dad then fills quantities, charges, and remarks into the Plik zbiorczy by hand
and declares Gotowość by starting Przebieg rozliczeń on that file, which creates
the Folder rozliczeń pracowników. The separate variants each start from their
own synthetic input; only this one hands the output of one process to the other.

## Sub-features

- `chain-handover` runs `run.py --source` on the Plik zbiorczy that `run_preparation.py` wrote, without any other change than the Gotowość entries.
- `chain-readiness` fills `N:AP` with non-zero quantities and `AQ:AT` with a charge description, charge, remark amount, and remark in three Wiersze danych; every other cell, formula, and `xl/externalLinks/*` part of the Plik zbiorczy stays as Przygotowanie wrote it.
- `chain-routing` gives every Wykonawca exactly their Zlecenia skuteczne in Plik zbiorczy order from row 18; Adrian's two are split by Kamil's in the Plik zbiorczy.
- `chain-columns` makes `A:AT` of every Wiersz danych in a Rozliczenie pracownika equal to its Plik zbiorczy row, Gotowość entries included.
- `chain-unsuccessful` keeps the Zlecenie nieskuteczne in the Rozliczenie wewnętrzne only, out of the Plik zbiorczy and every Rozliczenie pracownika.
- `chain-preserve` leaves every cell of the Wzorzec rozliczenia pracownika outside the Wiersze danych unchanged in each Rozliczenie pracownika, with byte-identical external links.
- `chain-safety` leaves the Rejestr zleceń and all three Wzorce byte-identical, and the Przebieg rozliczeń leaves the Rozliczenie wewnętrzne and the Plik zbiorczy byte-identical.
- `chain-metrics` appends one `DRY-RUN` and one `RUN` record to the history of each process.
- `chain-real-templates` (local only) runs the same path on byte copies of the three real Wzorce from `config/`.

## How to get to it (user POV)

- Dad double-clicks `Przygotuj plik zbiorczy.cmd`, then fills the Plik zbiorczy in Excel, saves it, and double-clicks `Utwórz rozliczenia.cmd`, picking that Plik zbiorczy.
- Direct verification passes every input explicitly: first `py -3 run_preparation.py --register <rejestr> --periods-directory <folder okresów> --period 08_14_09_2026 --config <mapping> --internal-template <wzorzec> --collective-template <wzorzec> --metrics <metrics> [--dry-run]`, then `py -3 run.py --source <Folder okresu>\Rozliczenie 08_14_09_2026 - zbiorcze.xlsx --config <mapping> --worker-template <wzorzec> --metrics <metrics> [--dry-run]`.

## Driving it with PowerShell and run.py

Preconditions:

- The orchestrator builds the `preparation` fixture plus a synthetic Wzorzec rozliczenia pracownika in the same layout as the Wzorzec pliku zbiorczego, with its own rate and an external link, and the same three-worker mapping, under a fresh run root.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant chain`. It runs the fixture, the doctor with `--with-worker-template`, the Przygotowanie dry-run and write with `assert_preparation.py`, `fill_readiness.py`, the Przebieg dry-run and write with `assert_chain.py`, cleanup, and the self-test. Success prints `VERIFY OK | variant=chain`; `--variant all` includes it, so the CI E2E job runs it.
- **Read the counts.** The Przygotowanie counts match `preparation`. The Przebieg dry-run plans 2 rows for Adrian Maciejewski, 1 for Darek Nowak, and 1 for Kamil Frontczak with `Problemy: 0`; the write reports three `ZAPISANO` results and `Zapisane szablony: 3`. Gotowość fills Adrian's two rows and Darek's row; Kamil's keeps the Wzorzec's zeros in `N:AP` and an empty `AQ:AT`.
- **Read the workbook proof.** `readiness.txt` has a `READINESS OK | … rows_filled=3 | columns=N:AT` line; the `ASSERT OK` line in `assert-settlement-run.txt` contains `rows_equal_plik_zbiorczy=A:AT | readiness_carried=true | unsuccessful_absent=true`. Every step file ends with its `exit_code`. A failure names the worker, row, and columns, never a value.
- **Check the real Wzorce.** When `config/` holds all three Wzorce, run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant chain-real-templates`; in a worktree the runner reads the main checkout's `config/`, and `--templates-dir` overrides that. Without them it prints `VERIFY SKIP`. It takes under a minute; the real Wzorce have about 10 000 rows each.
- **Drive the launcher chain.** On Windows run `py -3 -m pytest tests/test_cmd_launcher.py::test_cmd_launchers_run_przygotowanie_then_przebieg_rozliczen_on_its_plik_zbiorczy -q`. In one disposable runtime it runs `Przygotuj plik zbiorczy.cmd` with explicit `--register`, `--periods-directory`, and `--period`, adds a synthetic Wzorzec rozliczenia pracownika, then runs `Utwórz rozliczenia.cmd "<Plik zbiorczy>"` without a Gotowość step, and checks exit code `0`, `Status końcowy: OK`, the three files of the Folder rozliczeń pracowników, and Adrian's first Zlecenie.

## Gotchas

- Before this variant the synthetic Plik zbiorczy of `default` had empty `O:AT`, so cutting the copy into a Szablon pracownika down to `A:N` still passed (found at #76). The Gotowość entries make `chain` fail with the columns named; keep them non-zero in every column of `N:AT`.
- The Gotowość step saves through the same external-link-preserving save as the processes, then checks every other cell and every `xl/externalLinks/*` part itself; Excel, which Dad uses, keeps them too.
- Przebieg rozliczeń copies `A:AT` by position, not by header, so the check compares positions; the real Wzorzec rozliczenia pracownika has `GODZINA` where the Wzorzec pliku zbiorczego has `MIASTO`.
- The two processes keep separate metrics histories with different counters; never point both CLIs at one file.
