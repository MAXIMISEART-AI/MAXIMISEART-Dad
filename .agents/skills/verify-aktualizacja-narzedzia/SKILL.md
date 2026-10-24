---
name: verify-aktualizacja-narzedzia
description: Model-check with TLA+ (TLC) that Aktualizacja narzędzia leaves Dad with a version that starts and with his own file in `config/`, and that the restart guardian rolls back only a new version that really does not start, under every order of failures - fetch, git, pip, file copy, restart guardian, a new version that will not start, the computer switching off, and Dad clicking the desktop shortcut during the restart. Use when a change touches `ToolClone.update`, `_DadFiles`, `_Journal`, `_roll_back`, `ToolUpdates._update` or `_restart`, `restart_guardian.main`, or the start in `launcher._start` in `src/rozliczenia/centrum/`, or when fixing #196.
pilnuje:
  - src/rozliczenia/centrum/tool_update.py
  - src/rozliczenia/centrum/tool_updates.py
  - src/rozliczenia/centrum/restart_guardian.py
  - src/rozliczenia/centrum/launcher.py
---

# Verify Aktualizacja narzędzia (TLA+)

## The promise

**TataMaDzialajacaWersje**: whenever no Aktualizacja narzędzia is in progress
(it finished, failed, or the computer switched off in the middle), either the
tool's clone stands on a version that starts from Dad's desktop shortcut and
Dad's file in `config/` (today `worker_mapping.yaml`, with his real names) has
his content, or the journal „Aktualizacja w toku” is still on disk and Dad's
content is on disk too, in the clone or in the journal's copy.

**Postep**: a journal in progress always disappears. The shortcut, the guardian,
Centrum or Dad's next click finishes the update or rolls it back. When it disappears with
nothing in progress, `TataMaDzialajacaWersje` again demands a version that
starts and Dad's content in the clone.

**OpiekunCofaTylkoNieudana**: the restart guardian rolls the clone back from
a new version (`restart_guardian.main`, `_rolled_back` after `_answers(new, …,
after)`) only when that version really would not start, also when Dad clicks
the desktop shortcut while the guardian restarts Centrum.

**OkienkoTylkoGdyNicNieDziala**: the restart guardian shows its native dialog
`not_started_after_update` only when no Centrum runs. After a rollback, the
port may already belong to the old version that Dad started from the shortcut,
and then the guardian ends without the dialog (`_runs(…, before)`, #368). The
promise leaves out the rollback after a port that was never released (see
Scope).

Harm: Dad clicks `Zaktualizuj narzędzie` in the middle of a settlement week and
is left with a tool that will not start, or with names that have turned back
into the repository's sample, and only Maks can repair it. For the second
promise: Dad loses an update that worked, sees `NOWA_WERSJA_NIE_WYSTARTOWALA`,
and Maks gets a Zgłoszenie about a version that starts fine. For the third:
Dad sees „Centrum rozliczeń nie wystartowało” while Centrum works.

ADR 0009 promises this as „Wszystko albo nic”, including the journal paragraph,
and „Opiekun … gdy nowa wersja nie wystartuje, cofa klon i uruchamia starą”
(#196).

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/AktualizacjaNarzedzia.tla`,
not the code. It describes the code only while you keep the two in step. Each
model action is one indivisible step of this code:

| Model action | Code (`src/rozliczenia/centrum/`) |
| --- | --- |
| `Klik` | `tool_updates.py` `ToolUpdates.start`, `_result` (`restart_guardian.prepare`). A click while a journal is in progress does not count toward `MaxKlikniec` (see Scope). |
| `Pobranie` | `tool_update.py` `ToolClone.update`: `_Journal.read`, and when no guardian may run (`guardian_may_run`) `_moved_back` before anything else (`cofa = "klik"`, `ROLLBACK_FAILED` when it fails); otherwise `_Git.fetch` of `main` and the Wydanie tags, `MainLine.newest()`, which is `newest_on_main` over `_main_tips`, the first-parent line of `main` (Wydania not on it are skipped; none left is `AKTUALNA`), `_Git.is_ancestor` (a clone that already contains the newest Wydanie is `AKTUALNA`), then up to `_DadFiles.leaving`, `_has_local_commits`, `_changed_tracked_files` |
| `KopiaPlikow` | `tool_update.py` `_Journal.begin`: `JournalKept` when a journal is in progress (only with a guardian's lease, since `Pobranie` rolls back any other), else copy and `fsync` of Dad's files into `pliki-taty`, then `stan.json` (`_write`) |
| `CheckoutHead` | `tool_update.py` `_DadFiles.set_aside` before `yield` |
| `Scalanie` | `tool_update.py` `ToolClone.update`, `git merge --ff-only`, and `if not moved` (`journal.end()`) when Git refuses |
| `PrzywroceniePoOdmowie`, `PrzywroceniePoScaleniu` | `tool_update.py` `_DadFiles.set_aside` `finally` (`_put_back`; its `OSError` becomes `_NotPutBack`) and `except _NotPutBack` in `ToolClone.update`: after the merge it calls `_moved_back`, before it returns `ROLLBACK_FAILED` and keeps the journal. After a refused merge or `except _NotSetAside` (`git checkout HEAD --` failed), `journal.end()`. |
| `Instalacja`, `InstalacjaKoniec` | `tool_update.py` `ToolClone._install_libraries` (`_Git.changed`, `pip_install`), the `try`/`except Exception` around it, and the `if installed is False` branch after it (both through `_moved_back`) |
| `CofanieUsun`, `CofanieReset`, `CofaniePrzywroc` | `tool_update.py` `_roll_back` (`_Journal.read` and `rev-parse HEAD` first), called by `ToolClone.update` through `_moved_back` or by `tool_updates.py` `ToolUpdates._moved_back` through `ToolClone.roll_back` (`cofa = "centrum"`), by `restart_guardian._rolled_back` through `ToolClone.roll_back` (`cofa = "opiekun"`, or `"opiekun_bez_portu"` when the port was never released), by `launcher._roll_back` through `ToolClone.roll_back` (`cofa = "skrot"`), or by `ToolClone.update` before fetching through `_moved_back` (`cofa = "klik"`) |
| `KoniecDziennika` | `tool_update.py` `_Journal.end` at the end of `_roll_back` and in `ToolClone.update` after a refusal; for `cofa = "skrot"` also `launcher._roll_back` (`write_result`) and `subprocess.call(restart_from_disk)` in `launcher._start`; for `cofa = "klik"` `ToolClone.update` goes on to `rev-parse HEAD` and the fetch |
| `Restart` | `tool_updates.py` `ToolUpdates._update` (restarts only on `UPDATED`), `_restart` (`ToolClone.leased_to_guardian` around `restart_guardian.launch`: it writes the lease and removes it when `launch` raises), and `_moved_back` when either raises |
| `OpiekunPort`, `OpiekunStart` | `restart_guardian.py` `main`: `_port_released` (waits while a shortcut holds the port), `write_result` (ok), `_start_centrum` (`run_centrum.py --bez-okienek`, which skips the journal), `_answers(new, …, after)`, then `_stop` and `_rolled_back`; without the port straight to `_rolled_back`. `OpiekunStart` is the moment the new Centrum takes the port in `launcher._listen_when_released`: with `--bez-okienek` it retries `listen_locally` for `_SHORTCUT_HOLDS_PORT_S`, so it waits while a shortcut holds the port (#246) |
| `OpiekunKoniec` | `restart_guardian.py` `main`: `ToolClone.confirm_update` after `_answers(new, …, after)` |
| `OpiekunPortStara`, `OpiekunStartStara` | `restart_guardian.py` `main` after a successful rollback of a version that did not answer: `_port_released` (fails while a Centrum started from the shortcut holds the port), `_start_centrum` (with `--bez-okienek`, so the old version waits for the shortcut's port like the new one), `_answers(…, before)` (also answered by that Centrum), then `_runs(…, before)`, which ends without a dialog when that Centrum holds the port. Every guardian path that ends in the dialog goes through `OpiekunOkienko` |
| `OpiekunOkienko` | `restart_guardian.py` `main`: `show_problem` with `not_started_after_update`, then `return 1`. It follows a failed rollback for the guardian (`CofaniePrzywroc`), the end of the journal after a rollback without the port (`KoniecDziennika`), a port held by another program after a rollback (`OpiekunPortStara`), and an old version that does not answer (`OpiekunStartStara`) |
| `Wylacz` | none: the computer switches off; the journal and its copy stay on disk |
| `DzierzawaMija` | none: `GUARDIAN_LEASE_S` passes after `lease_to_guardian` (`InterruptedUpdate.guardian_may_run`) |
| `Skrot` | `launcher.py` `_start` from the shortcut while nothing runs, as one step: `listen_locally`, `ToolClone.interrupted_update`, then the Komunikat `update_finishing` while `guardian_may_run`, `launcher._roll_back`, or the normal start (only "does it start") |
| `SkrotWTrakcie` | `launcher.py` `_start` from the shortcut while the guardian runs and no Centrum holds the port: `listen_locally` succeeds and the shortcut holds the port. When a Centrum holds it, `listen_locally` raises and the shortcut only asks `running_centrum`; nothing on disk changes, so the model leaves that case out |
| `SkrotOddajePort` | `launcher.py` `_start` after `listen_locally`: `ToolClone.interrupted_update`, `guardian_may_run`, then `listener.close()` and `update_finishing`; with no journal left (the guardian already rolled back) the normal start, which keeps the port |

Covered files: `src/rozliczenia/centrum/tool_update.py`,
`src/rozliczenia/centrum/tool_updates.py`,
`src/rozliczenia/centrum/restart_guardian.py`,
`src/rozliczenia/centrum/launcher.py`.

Sync commit: `1ad3469` (2026-10-24, #368: after a rollback,
`restart_guardian.main` asks the port `_runs(…, before)` before the dialog and
ends without it when the old version from the shortcut answers; the model
gained `OpiekunOkienko` and the promise `OkienkoTylkoGdyNicNieDziala`, without the rollback after an unreleased port). At this commit every row above was checked against the code.

A change matters when it changes the order of these steps, adds or removes a
step that touches the clone, Dad's files, the libraries or the running Centrum,
changes which exception is caught where, or adds a new way to fail. Changes to
Komunikaty text, the card, the log or Zgłoszenia do not matter here.

## Bring the model in line, then run

Do this for your own change and for a change you review. Update the model
before you trust a verdict. With an outdated model the check passes on code it
no longer describes.

1. Read the diff of the covered files since the sync commit
   (`git diff <sync commit> -- <covered files>`). For each hunk, find its row in
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
| `git` | the above + a new version that may not start + `GitFailed` from `git checkout HEAD --`, `git diff`, `git reset --keep` | passes |
| `kopiowanie` | the above without git + `shutil.copy2` of Dad's file or a write of `stan.json` raises `OSError` | passes |
| `nieudany-start` | `zwykle-awarie` + the new version does not answer in `START_TIMEOUT_S` | passes |
| `wylaczenie` | `nieudany-start` + the computer switches off at any step | passes |
| `skrot-w-trakcie` | `nieudany-start` + Dad clicks the desktop shortcut up to twice (`MaxSkrotowWTrakcie = 2`) while the guardian runs | passes |

Every configuration checks the invariants `TataMaDzialajacaWersje`,
`OpiekunCofaTylkoNieudana` and `OkienkoTylkoGdyNicNieDziala` and the liveness
property `Postep`, under the fairness in `Sprawiedliwosc` (see Scope). A broken invariant prints
`naruszone <name>:` and its harm in one sentence.
A broken `Postep` prints `naruszony Postep` and a counterexample that ends in a
loop: `(dalej nic sie nie dzieje)` or `(stad znow krok n i tak bez konca)`.

TLC stops at the first counterexample, so a configuration with a known finding
runs twice, both times with the `…PozaZnanymi` variant of every invariant
(`PROMISES` in the script) and `PostepPozaZnanymi`. They excuse any behaviour in which a step tagged with an
excused finding happened (`Slad(...)` adds the tag to `slady`, and `Znane`
checks it).

1. Excusing every other known finding (every `wybacz` in
   `model/oczekiwane.json`), it must break. The printed counterexample is this
   finding. If it passes, the finding is gone.
2. Excusing every known finding, it must pass. If it breaks, the promise
   fails in a way no known finding explains, and that is reported as new.

## Known findings

None.

Fixed:

- #246 (`skrot_zajmuje_port`, `skrot-w-trakcie`): Dad clicked the desktop
  shortcut while the guardian restarted Centrum. The shortcut held the port
  between `listen_locally` and `listener.close()`, the new Centrum ended with
  `PORT_ZAJETY`, and the guardian rolled back a version that works. Centrum
  started with `--bez-okienek` now retries `listen_locally` for
  `_SHORTCUT_HOLDS_PORT_S` (10 s); the old version after a rollback starts
  the same way.
- #212 (`bez_opiekuna`): Centrum rolls the clone back when
  `restart_guardian.launch` raises, and the guardian rolls it back when the
  port is not released, then shows the dialog.
- #213 (`wylaczenie`): the journal „Aktualizacja w toku” survives a
  switch-off, and the next start from the shortcut rolls the clone back from
  it before it loads any library.
- #210 (`reset`) and #211 (`kopiowanie`): a failed `git reset --keep` or
  `copy2` in Centrum keeps the journal, and Dad's next click rolls the clone
  back from it before it fetches. Before, that click answered `AKTUALNA` on
  the new commit, and nothing in Centrum finished the journal.

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
shortcut's own rollback), up to two shortcut clicks while the guardian runs
(`skrot-w-trakcie`, with the guardian's failures and a new version that may not
start, but without switch-offs or Git and copy failures), and all eight kinds
of new version.

`Postep` holds only under these assumptions (`Sprawiedliwosc` and the premise
of `Postep`):

- Running code takes its next step, Dad clicks again while Centrum runs and
  he has clicks left, and he starts the shortcut while Centrum is not running.
- After `COFNIECIE_NIEUDANE` Dad clicks again, as the Komunikat tells him.
  These clicks do not count toward `MaxKlikniec`; with them counted, two
  clicks used before a failed rollback leave the journal for good.
- Git and copy failures are transient: a rollback retried without end
  succeeds at some point (strong fairness on `CofanieResetUdane` and
  `CofaniePrzywrocUdane`). A disk that fails for good leaves the journal and
  a Komunikat startu at every start.
- The computer switches off finitely many times.
- `GUARDIAN_LEASE_S` (10 minutes) passes at some point, also while Dad keeps
  clicking (strong fairness), and only when no code runs and no shortcut
  holds the port (it holds it for a moment). The guardian takes at most twice `PORT_TIMEOUT_S` plus twice
  `START_TIMEOUT_S` plus a rollback, well under 10 minutes. A shortcut start
  while the guardian runs is modelled (`skrot-w-trakcie`, at most
  `MaxSkrotowWTrakcie` clicks, so `Postep` does not have to survive endless
  clicking). Not covered: a computer that sleeps longer than the lease while
  the guardian waits, after which a shortcut start could roll back under the
  guardian.

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
- A shortcut clicked while the guardian runs gives the port back within
  `_SHORTCUT_HOLDS_PORT_S` (10 s), because between `listen_locally` and
  `listener.close()` it only reads the journal on the local disk. The model
  lets `OpiekunStart` and `OpiekunStartStara` wait for it without a limit. A
  shortcut process that stalls longer brings `skrot_zajmuje_port` back. No
  promise checks the wait in `OpiekunStartStara`: without it the old version
  ends with `PORT_ZAJETY`, and `_runs(…, before)` still finds the shortcut's
  Centrum, so Dad sees no dialog either way.
- `OkienkoTylkoGdyNicNieDziala` leaves out the rollback after a port that was
  never released (`cofa = "opiekun_bez_portu"`). There the guardian shows the
  dialog without asking the port, because the old Centrum that did not close
  may still answer `health` in commit `before`. If the port's holder lets go
  during that rollback and Dad's shortcut takes the port, Dad sees the dialog
  while Centrum runs. With that exception removed, the check breaks with
  exactly this counterexample.
- A shortcut whose `listen_locally` fails only asks `running_centrum` and
  changes nothing on disk, so the model leaves it out. Its wrong Komunikaty
  are not checked: `PORT_ZAJETY` when Centrum is still starting and does not
  answer `health` in 5 s, `INNA_WERSJA_CENTRUM` while the old Centrum is still
  closing.
- Not covered: what the card or a Komunikat shows (only whether the
  guardian's dialog appears), the Centrum log, `RunHost` refusals during an
  Uruchomienie procesu, the result file, and whether the browser reconnects.
  For those use `verify-centrum-rozliczen` with `--feature aktualizacja`.
