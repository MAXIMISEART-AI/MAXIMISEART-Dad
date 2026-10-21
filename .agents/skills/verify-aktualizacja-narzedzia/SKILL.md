---
name: verify-aktualizacja-narzedzia
description: Model-check with TLA+ (TLC) that Aktualizacja narzędzia leaves Dad with a version that starts and with his own file in `config/`, under every order of failures - fetch, git, pip, file copy, restart guardian, a new version that will not start, and the computer switching off. Use when a change touches `ToolClone.update`, `_DadFiles`, `_Journal`, `_roll_back`, `ToolUpdates._update` or `_restart`, `restart_guardian.main`, or the start in `launcher._start` in `src/rozliczenia/centrum/`, or when fixing #196.
---

# Verify Aktualizacja narzędzia (TLA+)

## The promise

**TataMaDzialajacaWersje**: whenever no Aktualizacja narzędzia is in progress
(it finished, failed, or the computer switched off in the middle), either the
tool's clone stands on a version that starts from Dad's desktop shortcut and
Dad's file in `config/` (today `worker_mapping.yaml`, with his real names) has
his content, or the journal „Aktualizacja w toku” is still on disk and Dad's
content is on disk too, in the clone or in the journal's copy.

**Postep**: a journal in progress always disappears. The shortcut, the guardian
or Centrum finishes the update or rolls it back. When it disappears with
nothing in progress, `TataMaDzialajacaWersje` again demands a version that
starts and Dad's content in the clone.

Harm: Dad clicks `Zaktualizuj narzędzie` in the middle of a settlement week and
is left with a tool that will not start, or with names that have turned back
into the repository's sample, and only Maks can repair it.

ADR 0009 promises this as „Wszystko albo nic”, including the journal paragraph,
and „Opiekun … gdy nowa wersja nie wystartuje, cofa klon i uruchamia starą”
(#196).

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/AktualizacjaNarzedzia.tla`,
not the code. It describes the code only while you keep the two in step. Each
model action is one indivisible step of this code:

| Model action | Code (`src/rozliczenia/centrum/`) |
| --- | --- |
| `Klik` | `tool_updates.py` `ToolUpdates.start`, `_result` (`restart_guardian.prepare`) |
| `Pobranie` | `tool_update.py` `ToolClone.update` up to `_DadFiles.leaving`, `_has_local_commits`, `_changed_tracked_files` |
| `KopiaPlikow` | `tool_update.py` `_Journal.begin`: `JournalKept` when a journal is in progress, else copy and `fsync` of Dad's files into `pliki-taty`, then `stan.json` (`_write`) |
| `CheckoutHead` | `tool_update.py` `_DadFiles.set_aside` before `yield` |
| `Scalanie` | `tool_update.py` `ToolClone.update`, `git merge --ff-only`, and `if not moved` (`journal.end()`) when Git refuses |
| `PrzywroceniePoOdmowie`, `PrzywroceniePoScaleniu` | `tool_update.py` `_DadFiles.set_aside` `finally` (`_put_back`; its `OSError` becomes `_NotPutBack`) and `except _NotPutBack` in `ToolClone.update`: after the merge it calls `_moved_back`, before it returns `ROLLBACK_FAILED` and keeps the journal. After a refused merge or `except _NotSetAside` (`git checkout HEAD --` failed), `journal.end()`. |
| `Instalacja`, `InstalacjaKoniec` | `tool_update.py` `ToolClone._install_libraries` (`_Git.changed`, `pip_install`), the `try`/`except Exception` around it, and the `if installed is False` branch after it (both through `_moved_back`) |
| `CofanieUsun`, `CofanieReset`, `CofaniePrzywroc` | `tool_update.py` `_roll_back` (`_Journal.read` and `rev-parse HEAD` first), called by `ToolClone.update` through `_moved_back` or by `tool_updates.py` `ToolUpdates._moved_back` through `ToolClone.roll_back` (`cofa = "centrum"`), by `restart_guardian._rolled_back` through `ToolClone.roll_back` (`cofa = "opiekun"`, or `"opiekun_bez_portu"` when the port was never released), or by `launcher._roll_back` through `ToolClone.roll_back` (`cofa = "skrot"`) |
| `KoniecDziennika` | `tool_update.py` `_Journal.end` at the end of `_roll_back` and in `ToolClone.update` after a refusal; for `cofa = "skrot"` also `launcher._roll_back` (`write_result`) and `subprocess.call(restart_from_disk)` in `launcher._start` |
| `Restart` | `tool_updates.py` `ToolUpdates._update` (restarts only on `UPDATED`), `_restart` (`ToolClone.lease_to_guardian`, then `restart_guardian.launch`), and `_moved_back` when either raises |
| `OpiekunPort`, `OpiekunStart` | `restart_guardian.py` `main`: `_port_released`, `write_result` (ok), `_start_centrum` (`run_centrum.py --bez-okienek`, which skips the journal), `_answers(new, …, after)`, then `_stop` and `_rolled_back`; without the port straight to `_rolled_back` |
| `OpiekunKoniec` | `restart_guardian.py` `main`: `ToolClone.confirm_update` after `_answers(new, …, after)` |
| `OpiekunPortStara`, `OpiekunStartStara` | `restart_guardian.py` `main` after a successful rollback of a version that did not answer: `_port_released`, `_start_centrum`, `_answers(…, before)`, or the dialog `not_started_after_update` |
| `Wylacz` | none: the computer switches off; the journal and its copy stay on disk |
| `DzierzawaMija` | none: `GUARDIAN_LEASE_S` passes after `lease_to_guardian` (`InterruptedUpdate.guardian_may_run`) |
| `Skrot` | `launcher.py` `_start` from the shortcut: `listen_locally`, `ToolClone.interrupted_update`, then the Komunikat `update_finishing` while `guardian_may_run`, `launcher._roll_back`, or the normal start (only "does it start") |

Covered files: `src/rozliczenia/centrum/tool_update.py`,
`src/rozliczenia/centrum/tool_updates.py`,
`src/rozliczenia/centrum/restart_guardian.py`,
`src/rozliczenia/centrum/launcher.py`.

Sync commit: `a713bc87d5c2` (#213's fix on top of
`integracja/180-aktualizacja-narzedzia`, 2026-10-21: the journal „Aktualizacja
w toku” and its rollback when the shortcut starts). At this commit every row
above was checked against the code.

A change matters when it changes the order of these steps, adds or removes a
step that touches the clone, Dad's files, the libraries or the running Centrum,
changes which exception is caught where, or adds a new way to fail. Changes to
Komunikaty text, the card, the log or Zgłoszenia do not matter here.

## Bring the model in line, then run

Do this for your own change and for a change you review. Update the model
before you trust a verdict. With an outdated model the check passes on code it
no longer describes.

1. Read the diff of the covered files since the sync commit
   (`git diff 0e3a773130dd -- <covered files>`). For each hunk, find its row in
   the table.
2. Change the matching actions so that one action stays one indivisible step
   of the code. Keep the comment that names the code. TLA+ strings must be
   ASCII (no Polish letters inside `"…"`), but comments may use them.
3. A new way to fail gets a `CONSTANT`, a branch guarded by it, and a line in
   every `.cfg`. Add it to the configuration whose theme fits, or give it its
   own `.cfg` with an entry in `model/oczekiwane.json`.
4. Run the check (next section).
5. Before you trust a pass on a new code path, break that path in the model
   (drop its rollback, say) and see the check fail. Before you trust a
   failure, read it as described in „Real bug or modeling error?”.
6. If the change rewrites the code behind a known finding, rewrite that
   finding below and its `znalezisko` in `model/oczekiwane.json` in the same
   change.
7. Move the sync commit forward only after you have checked every row of the
   table against the code at the new commit, and only when you commit the
   model with that code.

## Run

```bash
.venv/bin/python .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
```

On Windows use `py -3 .agents\skills\verify-aktualizacja-narzedzia\scripts\sprawdz_aktualizacje.py`.
In a worktree, create its `.venv` first (`python3 tools/setup_worktree.py`).
No system Java is needed. The first run downloads pinned `jdk4py==25.0.2.1`
(a Java runtime packaged for pip, about 50 MB) and `tla2tools.jar` v1.7.4
(TLC 2.19, SHA-256 checked) into `.verification/formal-aktualizacja/`, which
Git ignores. After that a run takes about 6 s, offline. `--config NAME` runs
one configuration, and `--strict` makes known findings exit 1.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `AKTUALIZACJA OK` | 0 | The promise holds in every configuration. |
| `AKTUALIZACJA OK, ZNANE ZNALEZISKA: n` | 0 | Only the known findings below break the promise. Each is printed with its counterexample, and every other path passes. |
| `AKTUALIZACJA: NOWE NARUSZENIE (n)` | 1 | The promise breaks in a way that is not a known finding. The counterexample is printed. |
| `AKTUALIZACJA: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding no longer happens. If you fixed it, set `"wynik": "przechodzi"` for it in `model/oczekiwane.json` and remove it from the findings below. |
| `AKTUALIZACJA: BŁĄD MODELU (n)` | 2 | TLC gave no verdict (a syntax error in the model), or `TypeOK` broke. Nothing is known about the promise. |

`UWAGA: pokryty kod zmienił się od …` means a covered file changed after the
sync commit. Until you have done „Bring the model in line”, the verdict above
it means nothing.

## Configurations

Each `model/*.cfg` turns on a set of failures. TLC explores every order of
steps and failures, for every kind of new version: it does or does not drop
Dad's file, it does or does not change `requirements.txt`, and (in every
configuration except `zwykle-awarie`) it does or does not start, so the
guardian's rollback meets every other failure too.

| Config | Failures on | Expected |
| --- | --- | --- |
| `zwykle-awarie` | merge refused (`ZMIANY_NA_KOMPUTERZE`), fetch fails (`BRAK_POLACZENIA`), pip fails (`INSTALACJA_BIBLIOTEK`), guardian does not start or the port is not released | passes |
| `git` | the above + a new version that may not start + `GitFailed` from `git checkout HEAD --`, `git diff`, `git reset --keep` | known finding `reset` |
| `kopiowanie` | the above without git + `shutil.copy2` of Dad's file raises `OSError` | known finding `kopiowanie` |
| `nieudany-start` | `zwykle-awarie` + the new version does not answer in `START_TIMEOUT_S` | passes |
| `wylaczenie` | `nieudany-start` + the computer switches off at any step | passes |

Every configuration checks the invariant `TataMaDzialajacaWersje` and the
liveness property `Postep`, under the fairness in `Sprawiedliwosc` (see Scope).
A broken `Postep` prints `naruszony Postep` and a counterexample that ends in a
loop: `(dalej nic sie nie dzieje)` or `(stad znow krok n i tak bez konca)`.

TLC stops at the first counterexample, so a configuration with a known finding
runs twice, both times with `TataMaDzialajacaWersjePozaZnanymi` and
`PostepPozaZnanymi`. They excuse any behaviour in which a step tagged with an
excused finding happened (`Slad(...)` adds the tag to `slady`, and `Znane`
checks it). Only a failure in Centrum, which keeps running, is tagged
(`SladCentrum`): the same failure in the guardian or the shortcut leaves the
journal, and the check must show that the next start finishes it.

1. Excusing every other known finding (every `wybacz` in
   `model/oczekiwane.json`), it must break. The printed counterexample is this
   finding. If it passes, the finding is gone.
2. Excusing every known finding, it must pass. If it breaks, the promise
   fails in a way no known finding explains, and that is reported as new.

## Known findings

Each was traced back to the code at the sync commit.

1. **`reset`** (config `git`, #210): `git reset --keep` in `_roll_back` fails in
   Centrum (after `pip_install` returns `False`, `_Git.changed` raises, or
   `restart_guardian.launch` raises), and the clone stays on the new commit.
   `_moved_back` gives `COFNIECIE_NIEUDANE` and the journal stays, so the next
   start from the shortcut rolls the clone back. But Centrum keeps running:
   Dad's next click answers `AKTUALNA` (or the fetch fails), nothing in Centrum
   touches the journal, and `Postep` breaks for as long as Centrum runs. The
   same failure in the guardian is no longer a finding: the journal stays, and
   the next start rolls back.
2. **`kopiowanie`** (#211): `copy2` of Dad's file from the copy raises `OSError`
   at the last restore in Centrum: in the `finally` of `_DadFiles.set_aside`
   after a refused merge, or in the `finally` of `_roll_back`. The
   repository's sample stays in place of Dad's file (or the file is gone), his
   content is only in the journal's copy, and Centrum shows
   `COFNIECIE_NIEUDANE`. The next start restores it, but while Centrum runs
   nothing does (`Postep` breaks the same way as for `reset`). A failed
   restore after `git merge --ff-only` rolls the clone back, and the same
   failure in the guardian or the shortcut leaves the journal for the next
   start.

#212 (`bez_opiekuna`) is fixed: Centrum rolls the clone back when
`restart_guardian.launch` raises, and the guardian rolls it back when the port
is not released, then shows the dialog. #213 (`wylaczenie`) is fixed: the
journal „Aktualizacja w toku” survives a switch-off, and the next start from
the shortcut rolls the clone back from it before it loads any library.

## Real bug or modeling error?

Read the counterexample as steps in the code's words, then check each step
against its row in the table:

- If every step is something the code can do, in that order, and the end state
  (`klon na wersji …, plik taty: …, biblioteki: …`) is what the disk would
  hold, it is a real bug. Report it with the counterexample. Do not weaken
  `TataMaDzialajacaWersje`, remove a failure, widen `Znane`, or change product
  code unless the user asks.
- If a step cannot happen in the code (an exception the code catches, an order
  the code does not allow, two code steps merged into one), the model is
  wrong. Fix the action and cite the line that proves it.
- `TypeOK` breaking is always a modeling error.

## Scope

Verified, with `MaxKlikniec = 2` and one newer `main` that does not move again
during the run: every order of the failures above, across both clicks, a
shortcut start after a failure or a switch-off (also a switch-off during the
shortcut's own rollback), and all eight kinds of new version.

`Postep` holds only under these assumptions (`Sprawiedliwosc` and the premise
of `Postep`):

- Running code takes its next step, Dad clicks again while Centrum runs and
  he has clicks left, and he starts the shortcut while Centrum is not running.
- Git and copy failures are transient: a rollback retried without end
  succeeds at some point (strong fairness on `CofanieResetUdane` and
  `CofaniePrzywrocUdane`). A disk that fails for good leaves the journal and
  a Komunikat startu at every start.
- The computer switches off finitely many times.
- `GUARDIAN_LEASE_S` (10 minutes) passes at some point, and only when no code
  runs. The guardian takes at most twice `PORT_TIMEOUT_S` plus twice
  `START_TIMEOUT_S` plus a rollback, well under 10 minutes. The model has no
  shortcut start while the guardian runs; in the code the lease makes such a
  start refuse with `AKTUALIZACJA_SIE_KONCZY`. Not covered: a computer that
  sleeps longer than the lease while the guardian waits, after which a
  shortcut start could roll back under the guardian.

Assumed, and not checked:

- Deleting `stan.json` (`_Journal.end`) succeeds. If it raises, every caller
  handles it like a failed rollback, and the journal stays for the next start.
- The clone stands on the journal's `przed` or `po` whenever it is read.
  Anything else (Maks changed the clone) is `JournalKept`: nothing is rolled
  back and the shortcut shows `NIEOCZEKIWANY_BLAD_STARTU`.

- Each Git command, each `copy2` and the guardian are indivisible. A switch-off
  in the middle of `git merge` (a half-updated working tree) is not modelled;
  the shortcut's `git reset --keep` would then meet a half-updated tree.
- The old version starts with any libraries, because `requirements.txt` has
  only lower bounds. Pip killed between uninstalling and installing a library
  could break this, so the `wylaczenie` model is optimistic.
- Dad has one file in `config/`. His untracked files (Wzorce, Ustawienia taty,
  the Zgłoszenia key, the log, metrics, period files) are not modelled. Git
  does not touch them, and when the new version would overwrite one, `merge`
  refuses.
- Not covered: what the card or the Komunikat shows, the Centrum log,
  `RunHost` refusals during an Uruchomienie procesu, the result file, and
  whether the browser reconnects. For those use `verify-centrum-rozliczen`
  with `--feature aktualizacja`.
