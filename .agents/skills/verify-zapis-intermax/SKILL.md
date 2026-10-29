---
name: verify-zapis-intermax
description: Exhaustively check that Uporządkowanie INTERMAX (`order_register` in `src/rozliczenia/intermax_ordering.py`) and Przywracanie Kopii INTERMAX (`restore` in `src/rozliczenia/intermax_copies.py`) replace the Rejestr zleceń only over the bytes they read, keep a Kopia INTERMAX with exactly the bytes they replaced and the 10 newest Kopie of both names, put exactly the chosen Kopia into INTERMAX, and leave INTERMAX, its folder and the Kopie as they were when they stop, under every order of a worker's change arriving through OneDrive, Dad opening INTERMAX in Excel, OneDrive refusing the replace, failed file steps, a failed write check and a killed process. Use when a change touches `order_register` (`before_replace`, `save`), `intermax_copies.make_copy`, `listed`, `keep_newest` or `restore`, `intermax_file.save` or `restore` (their retried replace and `Waiting`), `Register.read` or `Register.check`, `workbook_save.write_atomically`, `workbook_files` reading or the Excel lock, adds another writer of INTERMAX or of the Kopie folder, or when `explore_intermax.py` fails.
pilnuje:
  - src/rozliczenia/intermax_ordering.py
  - src/rozliczenia/intermax_copies.py
  - src/rozliczenia/intermax_file.py
  - src/rozliczenia/workbook_save.py
  - src/rozliczenia/workbook_files.py
ci: .agents/skills/verify-zapis-intermax/scripts/explore_intermax.py
---

# Verify zapis INTERMAX

## What CI runs and what stays local

CI runs `explore_intermax.py` (the `ci:` key) in Mutation checks whenever a change touches this skill,
and `check_intermax_mutations.py` in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`). Run
them locally only to reproduce a red Mutation checks step or the night's issue, or while you work on the
checker. What stays with you on every change to the covered code is „Does the
change touch it?”: a new step between the read and the replace, a third writer of INTERMAX or of the
Kopie folder (beside Uporządkowanie and Przywracanie Kopii INTERMAX, #472) or a new file next to INTERMAX
passes the check without being checked until the checker has a point for it. Sorting a red run as „When the
check fails” says also stays with you.

## The promise

INTERMAX is the only record of orders since 2021, in OneDrive, and the
workers edit it on their own computers (ADR 0019). Two pieces of code
replace it: Uporządkowanie INTERMAX and Przywracanie Kopii INTERMAX from
Konfiguracja (#472). Each rule holds for both; „the run” is either.

- **BEZ_UTRATY_ZMIAN**: when the run replaces INTERMAX, it replaces the bytes
  it read. ADR 0019: Uporządkowanie „zmienia tylko Surowe zlecenia”, and every
  other part and row „zostają bajt w bajt”. Harm: a worker's change saved on
  another computer during the run is gone, and nobody sees it go.
- **KOPIA_ZASTAPIONEGO**: when the run replaces INTERMAX, a Kopia INTERMAX holds
  exactly the bytes it replaced (ADR 0019: „Przed każdą podmianą powstaje Kopia
  INTERMAX”). Harm: restoring the Kopia does not bring back what was there.
- **ZATRZYMANIE_BEZ_SLADU**: a run that stops, or ends in any other
  exception before the replace, leaves INTERMAX as it was, no temporary file next to it, and the
  same Kopie, names and bytes, as before
  (docstring of `order_register`: „INTERMAX zostaje wtedy nietknięty”, „gdy
  podmiana się nie uda, Kopia znika”). Harm: a stray file in Dad's OneDrive, a
  Kopia of a change that never happened, or Dad's earlier Kopie gone.
- **SUKCES**: a run that returns a summary has replaced INTERMAX and left no
  temporary file.
- **PRZYWROCONA_KOPIA**: a restore that returns has replaced INTERMAX with
  exactly the bytes of the chosen Kopia (#472: „INTERMAX jest bajt w bajt
  wybraną Kopią”). Harm: Dad clicks „Przywróć tę kopię” and still has the
  broken INTERMAX.
- **KOPIE_NAJNOWSZE**: after a summary the Kopie folder holds the
  `intermax_copies.KEPT` (10) newest Kopie of both names (`przed
  uporządkowaniem`, `przed przywróceniem`) by the moment in their name, the new
  one among them, unless removing older ones failed, which the code turns into
  a warning. Harm: Dad loses the Kopia he needs, or the folder grows forever.
- **BEZ_WYJATKU**: the run ends with a summary or a `StopError`, or the process
  dies; no other exception escapes. Harm: Dad sees an unexpected error instead
  of a Komunikat that tells him what to do.

## Does the change touch it?

The checker runs the real `order_register` and the real
`intermax_copies.restore`, and wraps eight steps to choose, before each, what
happens first. Each is one indivisible step of this code:

| Point in the checker | Code (`src/rozliczenia/`) |
| --- | --- |
| after the read | `intermax_file.Register.read` (`workbook_files.workbook_content`), called in `order_register.read`; in the restore the first `workbook_content` of INTERMAX |
| the Excel lock check | `workbook_files.is_open_in_excel` on INTERMAX, in `ensure_available` (`check`, `Register.read`, `workbook_content`), in both `before_replace` and in the restore's sorting of a failed replace |
| the temporary file | `temporary.write_bytes(content)` in `intermax_file.save`, inside `workbook_save.write_atomically`; may raise `OSError` |
| the write check | `Register.check` on the re-read temporary file in `intermax_file.save`; may find a mismatch (`WriteMismatch`). The restore compares bytes and has no such point |
| the Kopia | `intermax_copies.make_copy(register.content, …)` in `before_replace`, after the write check; in the restore `make_copy(current, …, "restore")`; may raise `OSError` |
| the replace | `os.replace` of the temporary file over INTERMAX in the `replace` that `intermax_file._replace` (for `save` and `restore`) gives `workbook_save.write_atomically`; may raise `OSError`, may be refused by OneDrive (`PermissionError` without the `~$` lock, which `save` retries), and raises `PermissionError` while the `~$` lock exists, as Windows does for a file Excel holds |
| the pause before a retry | `waiting.pause` in that `replace`, after a refusal and before it reads INTERMAX again (`workbook_content`) and retries; may last the whole retry time (`_RETRY_S`), so the next refusal ends in `HeldByOneDrive`. The checker's `Waiting` clock moves only in this pause and never sleeps |
| the old Kopie | `intermax_copies.keep_newest` after the replace; may raise `OSError`, which `order_register` and `restore` turn into a warning |

At each point, before the step, a worker may save a change on another
computer, which OneDrive puts in place as a new INTERMAX (not while Excel holds
INTERMAX: OneDrive then keeps a conflict copy beside it, which the checker
leaves out), Dad may open INTERMAX in Excel (the `~$` lock file), the step may
fail, or the process may die.

Covered files: `src/rozliczenia/intermax_ordering.py`,
`src/rozliczenia/intermax_copies.py` (`make_copy`, `listed`, `keep_newest`,
`restore`), `src/rozliczenia/intermax_file.py`
(`Register.read`, `Register.check`, `save`, `restore`, `_replace`), `src/rozliczenia/workbook_save.py`
(`write_atomically`), and `src/rozliczenia/workbook_files.py`
(`workbook_content`, `ensure_available`, `is_open_in_excel`,
`excel_lock_file`).

**Sync commit: `c567dff6`** (2026-10-26, #472: Przywracanie Kopii INTERMAX through the same retried replace, the
limit of 10 over both names). At this commit the
checker was confirmed to describe the code above. To see whether it needs
another look:

```bash
git log --oneline c567dff6..HEAD -- src/rozliczenia/intermax_ordering.py src/rozliczenia/intermax_copies.py src/rozliczenia/intermax_file.py src/rozliczenia/workbook_save.py src/rozliczenia/workbook_files.py
```

Read each listed commit against the table. A change matters when it adds,
removes or reorders a step between the read and the replace, changes what the
Kopia is made from or when it or older Kopie disappear, adds another writer of
INTERMAX or of the Kopie folder, or catches different exceptions. Changes to
recognising and ordering the Surowe zlecenia (`raw_orders`,
`Register.ordered`, what `Register.check` compares) and to Komunikaty do not
matter here. Move the sync commit forward only after the checker matches the
code at the new commit and the check and its mutations pass there.

## Run

```bash
.venv/bin/python .agents/skills/verify-zapis-intermax/scripts/explore_intermax.py
```

On Windows use `py -3` instead of `.venv/bin/python`. In a worktree, create its
`.venv` first (`python3 tools/setup_worktree.py`). It needs nothing beyond the
repo's Python, writes only into a temporary directory, and takes a few seconds.
`--strict` counts known findings as violations too.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `INTERMAX OK` | 0 | Every rule holds in every schedule. |
| `INTERMAX OK, ZNANE USTALENIA: n` | 0 | Only the known findings below, each printed with its shortest counterexample. |
| `INTERMAX: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below. The counterexample is printed. |
| `INTERMAX: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding no longer happens. If a change fixed it, delete it from `KNOWN_FINDINGS` and from this file. |

## How it works and what it covers

`explore_intermax.py` writes three synthetic INTERMAX files with
`tests/fixtures/intermax.py`: the original, with a day of Surowe zlecenia at the
bottom, the version a worker saves on another computer, with one more
ordered order above them, and an earlier one with one ordered order fewer. For
every schedule it puts the original into a fresh folder, fills the Kopie folder
with 10 older Kopie (earlier days, alternately `przed przywróceniem` and `przed
uporządkowaniem`, so that their order by name differs from their order in time;
the oldest holds the earlier INTERMAX, the others their own bytes), runs
`order_register` or `restore` of the oldest Kopia, and picks at every point in
the table. It re-runs the code from scratch for every schedule.

Bounds: at most one worker's change, one Excel opening, one failed file step,
one failed write check, two OneDrive refusals of the replace, one pause that
lasts the whole retry time and one killed process per run. That is 1780
schedules: 895 of Uporządkowanie and 885 of the restore (305 before the
retried replace, #505).

Not covered:

- the content of the ordered day (`raw_orders`, `Register.ordered`, what
  `Register.check` compares), which `tests/test_uporzadkowanie_intermax.py`
  covers;
- a worker's change between two steps inside one point (the checker treats
  `os.replace` as atomic, as it is on NTFS);
- `copy.unlink()` failing after a failed replace;
- two runs at once (Centrum runs one Uruchomienie at a time,
  `verify-jedno-uruchomienie-naraz`);
- what a killed process leaves: the checker kills by raising at a point, so
  `finally` blocks still run and remove the temporary file, which a real kill
  would leave in OneDrive with a Kopia of a replace that never happened. After
  a kill only BEZ_UTRATY_ZMIAN and KOPIA_ZASTAPIONEGO are checked, when the
  replace happened;
- the restore's own checks before its first step (the Kopia missing, open in
  Excel or not a workbook), which `tests/test_centrum_przywracanie_kopii_intermax.py`
  covers, and a restore running beside an Uruchomienie, which `RunHost` refuses
  (`verify-jedno-uruchomienie-naraz`);
- the order of Kopie by the moment in their name around a clock change.

## Known findings

1. **BEZ_UTRATY_ZMIAN and KOPIA_ZASTAPIONEGO: a worker's change that arrives
   during the run is lost.** The same holds for the restore, whose Kopia of the
   current state is made from the bytes it read (`current`). The steps:
   1. `Register.read` reads INTERMAX;
   2. `before_replace` writes the Kopia INTERMAX from `register.content`;
   3. a worker saves a change on another computer, and OneDrive replaces
      INTERMAX with it;
   4. `os.replace` puts the ordered file, made from the bytes read in step 1,
      over the worker's version;
   5. `order_register` returns its summary.

   The worker's change is in neither INTERMAX nor the Kopia. The window runs
   from the read to the first attempt of the replace: planning, writing the
   temporary file and reading it back, and the Kopia, seconds for Dad's 6.5 MB
   file. Nothing between them compares INTERMAX on disk with
   `register.content`. After OneDrive refuses the replace, `save` waits, reads
   INTERMAX again and retries only over the bytes it read, so the window of a
   retry runs from that re-read to the retried `os.replace`. The checker shows
   the finding there too, because a point sits between them. No `os.replace` on
   Windows replaces only a file that is unchanged.

   BEZ_UTRATY_ZMIAN is excused only when a worker's change arrived after the
   read and before the replace, neither followed by an OneDrive refusal nor in
   the pause before a retry, the run read the original and replaced the
   worker's version (`_worker_change_lost`). A worker's change followed by a
   refusal is one the run had a pause to see, and one that arrived in that
   pause is one the re-read after it sees, so losing either is a new violation.
   KOPIA_ZASTAPIONEGO
   is excused only in the same story with a Kopia of the bytes read
   (`_copy_of_what_was_read`).
   The same rules broken in any other schedule are a new violation.

2. **BEZ_WYJATKU: an `OSError` from writing the temporary file escapes as an
   unexpected error.** `temporary.write_bytes(content)` in `intermax_file.save`
   raises (a full disk, OneDrive or an antivirus holding the file).
   `write_atomically` turns an `OSError` from creating the temporary file
   (`tempfile.mkstemp`, `os.close`) and from `os.replace` into
   `WorkbookSaveError`, but not one from writing its content, and
   `order_register.save` catches only `WriteMismatch`, `UnsupportedShape` and
   `WorkbookSaveError`, so the `OSError` leaves `order_register`. INTERMAX is
   unchanged, the temporary file is removed and the Kopie stay as they were
   (ZATRZYMANIE_BEZ_SLADU checks it), but Dad sees an unexpected error instead
   of a Komunikat. Excused only after that failure, with no replace and with
   the injected `PermissionError` as the exception that left
   (`_temporary_write_failed`).

A known finding lives in `KNOWN_FINDINGS` in `explore_intermax.py` with the
story after which it is excused. When a code change fixes it, the check ends
with `ZNALEZISKO ZNIKNĘŁO`: delete the entry there and here.

## When the check fails

Read the counterexample as a story. Each numbered line is one step: a step of
`order_register` in the code's words, a worker's change or Dad opening Excel,
a failed step, or a dead process. Then sort it:

- **Real bug**: every step can happen at Dad's (OneDrive replacing the file
  with a worker's version, Excel's `~$` lock, a locked file or full disk,
  Centrum closed), and the end state breaks the rule as stated above. Report it
  with the story. Fix the product code only if the user asks.
- **Modeling error**: a step Windows or OneDrive would not do, or a point the
  code cannot reach. Fix `_points`, `World` or `act` in `explore_intermax.py`,
  and say what was wrong.
- **BEZ_WYJATKU**: the printed type and message name the exception; find where
  `order_register` lets it out.

Never shrink a bound or a rule to make a real counterexample go away.

## After changing the checker or an intended change to the save

CI proves the check can still fail. The night on `main` runs
`.agents/skills/verify-zapis-intermax/scripts/check_intermax_mutations.py`
after a change of this skill's folder. It applies each broken variant to a
temporary copy of the checkout (`tools/mutacje.py`) and must end with
`MUTACJE OK`. Each of these gives `INTERMAX: NOWE NARUSZENIE`:

- a replace without a Kopia;
- a Kopia of other bytes than those read;
- a Kopia left after a failed replace;
- a Kopia left after the Zatrzymanie for OneDrive (`HeldByOneDrive`);
- an `OSError` from `keep_newest` that escapes;
- a temporary file left after a failed replace;
- older Kopie sorted the wrong way round;
- one Kopia kept instead of 10;
- a failed replace that removes every Kopia;
- a retried replace that does not read INTERMAX again after the pause;
- a retried replace that reads INTERMAX again before the pause instead of
  after it;
- the Kopia made before the write check;
- Kopie sorted by name instead of by the moment in their name;
- a restore without the Kopia of the current state;
- the Kopia of the current state left after a failed restore;
- a restore that replaces INTERMAX with the bytes it read instead of the
  chosen Kopia.

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its
`anchor` and `replacement` against the new code so that it breaks the same
rule again.
