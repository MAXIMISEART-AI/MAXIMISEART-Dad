---
name: verify-zapis-intermax
description: Exhaustively check that Uporządkowanie INTERMAX (`order_register` in `src/rozliczenia/intermax_ordering.py`) replaces the Rejestr zleceń only over the bytes it read, keeps a Kopia INTERMAX with exactly the bytes it replaced, and leaves INTERMAX, its folder and the Kopie as they were when it stops, under every order of a worker's change arriving through OneDrive, Dad opening INTERMAX in Excel, file errors and a killed process. Use when a change touches `order_register` (`before_replace`, `save`), `intermax_copies.make_copy` or `keep_newest`, `intermax_file.save` or `Register.read`, `workbook_save.write_atomically`, adds Przywracanie Kopii INTERMAX (#472), or when `explore_intermax.py` fails.
pilnuje:
  - src/rozliczenia/intermax_ordering.py
  - src/rozliczenia/intermax_copies.py
  - src/rozliczenia/intermax_file.py
  - src/rozliczenia/workbook_save.py
ci: .agents/skills/verify-zapis-intermax/scripts/explore_intermax.py
---

# Verify zapis INTERMAX

## What CI runs and what stays local

CI runs `explore_intermax.py` (the `ci:` key) and `check_intermax_mutations.py` in Mutation checks
whenever a change touches this skill. Run them locally only to reproduce a red Mutation checks step, or
while you work on the checker. What stays with you on every change to the covered code is „Does the
change touch it?”: a new step between the read and the replace, a second writer of INTERMAX (such as
Przywracanie Kopii INTERMAX, #472) or a new file next to it passes the check without being checked
until the checker has a point for it. Sorting a red run as „When the check fails” says also stays
with you.

## The promise

INTERMAX is the only record of orders since 2021, in OneDrive, and the
workers edit it on their own computers (ADR 0019).

- **BEZ_UTRATY_ZMIAN**: when the run replaces INTERMAX, it replaces the bytes
  it read. ADR 0019: Uporządkowanie „zmienia tylko Surowe zlecenia”, and every
  other part and row „zostają bajt w bajt”. Harm: a worker's change saved on
  another computer during the run is gone, and nobody sees it go.
- **KOPIA_ZASTAPIONEGO**: when the run replaces INTERMAX, a Kopia INTERMAX holds
  exactly the bytes it replaced (ADR 0019: „Przed każdą podmianą powstaje Kopia
  INTERMAX”). Harm: restoring the Kopia does not bring back what was there.
- **ZATRZYMANIE_BEZ_SLADU**: a run that stops leaves INTERMAX as it was, no
  temporary file next to it and no new Kopia (docstring of `order_register`:
  „INTERMAX zostaje wtedy nietknięty”, „gdy podmiana się nie uda, Kopia
  znika”). Harm: a stray file in Dad's OneDrive, or a Kopia of a change that
  never happened.
- **SUKCES**: a run that returns a summary has replaced INTERMAX and left no
  temporary file.
- **BEZ_WYJATKU**: the run ends with a summary or a `StopError`, or the process
  dies; no other exception escapes.

## Does the change touch it?

The checker runs the real `order_register` and wraps five functions to choose,
before each, what happens first. Each is one indivisible step of this code:

| Point in the checker | Code (`src/rozliczenia/`) |
| --- | --- |
| after the read | `intermax_file.Register.read` (`workbook_files.workbook_content`), called in `order_register.read` |
| the Excel lock check | `workbook_files.is_open_in_excel` on INTERMAX, in `ensure_available` (`check`) and in `before_replace` |
| the Kopia | `intermax_copies.make_copy(register.content, …)` in `before_replace`; may raise `OSError` |
| the replace | `os.replace` of the temporary file over INTERMAX in `workbook_save.write_atomically`, after `intermax_file.save` wrote and checked it and called `before_replace`; may raise `OSError`, and raises `PermissionError` while the `~$` lock exists, as Windows does for a file Excel holds |
| the old Kopie | `intermax_copies.keep_newest` after the replace; may raise `OSError`, which `order_register` turns into a warning |

At each point, before the step, a worker may save a change on another
computer, which OneDrive puts in place as a new INTERMAX, Dad may open INTERMAX
in Excel (the `~$` lock file), the step may fail, or the process may die.

Covered files: `src/rozliczenia/intermax_ordering.py`,
`src/rozliczenia/intermax_copies.py`, `src/rozliczenia/intermax_file.py`
(`Register.read`, `save`), `src/rozliczenia/workbook_save.py`
(`write_atomically`), and `workbook_files.is_open_in_excel`.

**Sync commit: `31bb7651`** (2026-10-26, `main` after #476). At this commit the
checker was confirmed to describe the code above. To see whether it needs
another look:

```bash
git log --oneline 31bb7651..HEAD -- src/rozliczenia/intermax_ordering.py src/rozliczenia/intermax_copies.py src/rozliczenia/intermax_file.py src/rozliczenia/workbook_save.py src/rozliczenia/workbook_files.py
```

Read each listed commit against the table. A change matters when it adds,
removes or reorders a step between the read and the replace, changes what the
Kopia is made from or when it disappears, adds another writer of INTERMAX or of
the Kopie folder, or catches different exceptions. Changes to recognising and
ordering the Surowe zlecenia (`raw_orders`, `Register.ordered`,
`Register.check`) and to Komunikaty do not matter here. Move the sync commit
forward only after the checker matches the code at the new commit and the
check and its mutations pass there.

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

`explore_intermax.py` writes two synthetic INTERMAX files with
`tests/fixtures/intermax.py`: the original, with a day of Surowe zlecenia at the
bottom, and the version a worker saves on another computer, with one more
ordered order above them. For every schedule it puts the original into a fresh
folder, runs `order_register` on it, and picks at every point in the table. It
re-runs the code from scratch for every schedule.

Bounds: at most one worker's change, one Excel opening, one failed step and one
killed process per run. That is 196 schedules.

Not covered: the content of the ordered day (`raw_orders`, `Register.ordered`,
`Register.check`, which pytest and `tests/test_uporzadkowanie_intermax.py`
cover), a worker's change between two steps inside one point (the checker
treats `os.replace` as atomic, as it is on NTFS), `copy.unlink()` failing after
a failed replace, two runs at once (Centrum runs one Uruchomienie at a time,
`verify-jedno-uruchomienie-naraz`), a process killed in the middle of writing
the Kopia, Przywracanie Kopii INTERMAX (#472, not built yet), and the
ordering of Kopie by name around a clock change.

## Known findings

1. **BEZ_UTRATY_ZMIAN and KOPIA_ZASTAPIONEGO: a worker's change that arrives
   during the run is lost.** The steps:
   1. `Register.read` reads INTERMAX;
   2. `before_replace` writes the Kopia INTERMAX from `register.content`;
   3. a worker saves a change on another computer, and OneDrive replaces
      INTERMAX with it;
   4. `os.replace` puts the ordered file, made from the bytes read in step 1,
      over the worker's version;
   5. `order_register` returns its summary.

   The worker's change is in neither INTERMAX nor the Kopia. The window runs
   from the read to the replace: planning, writing the temporary file and
   reading it back, and the Kopia, seconds for Dad's 6.5 MB file. Nothing
   between them compares INTERMAX on disk with `register.content`. A re-read
   in `before_replace` right before `os.replace` would shrink the window to the
   time between that re-read and the replace. The checker would still show
   the finding there, because a point sits between them. No `os.replace` on
   Windows replaces only a file that is unchanged.

   Both findings are excused only after a worker's change arrived after
   `Register.read` (`_worker_after_read`). The same rules broken in any other
   schedule are a new violation.

A known finding lives in `KNOWN_FINDINGS` in `explore_intermax.py`. When a
code change fixes it, the check ends with `ZNALEZISKO ZNIKNĘŁO`: delete the
entry there and here.

## When the check fails

Read the counterexample as a story. Each numbered line is one step: a step of
`order_register` in the code's words, a worker's change or Dad opening Excel,
a failed step, or a dead process. Then sort it:

- **Real bug**: every step can happen at Dad's (OneDrive replacing the file
  with a worker's version, Excel's `~$` lock, a locked file, Centrum closed),
  and the end state breaks the rule as stated above. Report it with the story.
  Fix the product code only if the user asks.
- **Modeling error**: a step Windows or OneDrive would not do, or a point the
  code cannot reach. Fix `_points` or `World` in `explore_intermax.py`, and say
  what was wrong.
- **BEZ_WYJATKU**: the printed type and message name the exception; find where
  `order_register` lets it out.

Never shrink a bound or a rule to make a real counterexample go away.

## After changing the checker or an intended change to the save

CI proves the check can still fail. Mutation checks runs
`.agents/skills/verify-zapis-intermax/scripts/check_intermax_mutations.py`
whenever a change touches this skill. It applies each broken variant to a
temporary copy of the checkout (`tools/mutacje.py`) and must end with
`MUTACJE OK`. Each of these gives `INTERMAX: NOWE NARUSZENIE`:

- a replace without a Kopia;
- a Kopia of other bytes than those read;
- a Kopia left after a failed replace;
- an `OSError` from `keep_newest` that escapes;
- a temporary file left after a failed replace.

A mutation reported as `NIEAKTUALNA` no longer matches its file: rewrite its
`anchor` and `replacement` against the new code so that it breaks the same
rule again.
