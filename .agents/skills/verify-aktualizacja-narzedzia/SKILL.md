---
name: verify-aktualizacja-narzedzia
description: Model-check with TLA+ (TLC) that Aktualizacja narzędzia leaves Dad with a version that starts and with his own file in `config/`, under every order of failures - fetch, git, pip, file copy, restart guardian, a new version that will not start, and the computer switching off. Use when a change touches `ToolClone.update`, `_DadFiles`, `_roll_back`, `ToolUpdates._update` or `_restart`, or `restart_guardian.main` in `src/rozliczenia/centrum/`, or when fixing #196.
---

# Verify Aktualizacja narzędzia (TLA+)

## The promise

**TataMaDzialajacaWersje**: whenever no Aktualizacja narzędzia is in progress
(it finished, failed, or the computer switched off in the middle), the tool's
clone stands on a version that starts from Dad's desktop shortcut, and Dad's
file in `config/` (today `worker_mapping.yaml`, with his real names) has his
content. Harm: Dad clicks `Zaktualizuj narzędzie` in the middle of a settlement
week and is left with a tool that will not start, or with names that have
turned back into the repository's sample, and only Maks can repair it.

ADR 0009 promises this as „Wszystko albo nic” and „Opiekun … gdy nowa wersja
nie wystartuje, cofa klon i uruchamia starą” (#196).

## Does the change touch it?

The check runs a hand-written TLA+ model, `model/AktualizacjaNarzedzia.tla`,
not the code. It describes the code only while you keep the two in step. Each
model action is one indivisible step of this code:

| Model action | Code (`src/rozliczenia/centrum/`) |
| --- | --- |
| `Klik` | `tool_updates.py` `ToolUpdates.start`, `_result` (`restart_guardian.prepare`, `backup.mkdir`) |
| `Pobranie` | `tool_update.py` `ToolClone.update` up to `_DadFiles.leaving`, `_has_local_commits`, `_changed_tracked_files` |
| `KopiaPlikow`, `CheckoutHead` | `tool_update.py` `_DadFiles.set_aside` before `yield` |
| `Scalanie` | `tool_update.py` `ToolClone.update`, `git merge --ff-only` |
| `PrzywroceniePoOdmowie`, `PrzywroceniePoScaleniu` | `tool_update.py` `_DadFiles.set_aside` `finally` (`_put_back`; its `OSError` becomes `_NotPutBack`) and `except _NotPutBack` in `ToolClone.update`: after the merge it calls `_moved_back`, before it returns `ROLLBACK_FAILED`. |
| `Instalacja`, `InstalacjaKoniec` | `tool_update.py` `ToolClone._install_libraries` (`_Git.changed`, `pip_install`), the `try`/`except Exception` around it, and the `if installed is False` branch after it (both through `_moved_back`) |
| `CofanieUsun`, `CofanieReset`, `CofaniePrzywroc` | `tool_update.py` `_roll_back`, called by `ToolClone.update` through `_moved_back` or by `tool_updates.py` `ToolUpdates._moved_back` through `ToolClone.roll_back` (`cofa = "centrum"`), or by `restart_guardian._rolled_back` through `ToolClone.roll_back` (`cofa = "opiekun"`, or `"opiekun_bez_portu"` when the port was never released) |
| `Restart` | `tool_updates.py` `ToolUpdates._update` (restarts only on `UPDATED`), `_restart`, and `_moved_back` when `restart_guardian.launch` raises |
| `OpiekunPort`, `OpiekunStart` | `restart_guardian.py` `main`: `_port_released`, `write_result` (ok), `_start_centrum`, `_answers(new, …, after)`, then `_stop` and `_rolled_back`; without the port straight to `_rolled_back` |
| `OpiekunPortStara`, `OpiekunStartStara` | `restart_guardian.py` `main` after a successful rollback of a version that did not answer: `_port_released`, `_start_centrum`, `_answers(…, before)`, or the dialog `not_started_after_update` |
| `Wylacz` | none: the computer switches off, and nothing runs at the next start to finish or undo the update |
| `Skrot` | `launcher.py` `main` started from the shortcut (only "does it start") |

Covered files: `src/rozliczenia/centrum/tool_update.py`,
`src/rozliczenia/centrum/tool_updates.py`,
`src/rozliczenia/centrum/restart_guardian.py`.

Sync commit: `6759ee38ec9a` (branch `review/180-poprawki`,
2026-10-21, with the rollbacks for #211 and #212). At this commit every row above was
checked against the code.

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
| `wylaczenie` | `nieudany-start` + the computer switches off at any step | known finding `wylaczenie` |

TLC stops at the first counterexample, so a configuration with a known finding
runs twice, both times with the invariant `TataMaDzialajacaWersjePozaZnanymi`.
That invariant excuses any behaviour in which a step tagged with an excused
finding happened (`Slad(...)` adds the tag to `slady`, and `Znane` checks it):

1. Excusing every other known finding (every `wybacz` in
   `model/oczekiwane.json`), it must break. The printed counterexample is this
   finding. If it passes, the finding is gone.
2. Excusing every known finding, it must pass. If it breaks, the promise
   fails in a way no known finding explains, and that is reported as new.

## Known findings

Each was traced back to the code at the sync commit.

1. **`reset`** (config `git`, #210): `git reset --keep` in `_roll_back` fails, and
   the clone stays on the new commit. In Centrum (after `pip_install` returns
   `False`, `_Git.changed` raises, or `restart_guardian.launch` raises),
   `_moved_back` gives `COFNIECIE_NIEUDANE`: the card no longer claims the
   old version runs and tells Dad to send it to Maks, but the new version may
   have no libraries and will not start from the shortcut (ADR 0010: no `.cmd`
   launchers to fall back on). In the guardian (`_rolled_back`), the new version that
   would not start stays, the result file says `COFNIECIE_NIEUDANE`, and Dad
   sees the dialog.
2. **`kopiowanie`** (#211): `copy2` of Dad's file from the copy raises `OSError`
   at the last restore: in the `finally` of `_DadFiles.set_aside` after a
   refused merge, or in the `finally` of `_roll_back` (in Centrum or the
   guardian). The repository's sample stays in place of Dad's file (or the
   file is gone); his content is only in `pliki-taty`, which then stays
   (`COFNIECIE_NIEUDANE` in Centrum, the dialog in the guardian). A failed
   restore after `git merge --ff-only` is no longer a finding: it rolls the
   clone back, and that rollback restores the file again.
3. **`wylaczenie`** (#213): the computer switches off anywhere from
   `git checkout HEAD --` to the end of the guardian's rollback
   (`OknoWylaczenia`). The shortest case is between `git merge --ff-only` and
   the end of `pip_install` (up to `_INSTALL_TIMEOUT_S`, 15 minutes): the
   clone stays on the new version without its libraries. Switching off while
   the guardian waits for the new version leaves a version nobody checked.
   Switching off in the middle of `set_aside` or `_roll_back` leaves Dad's
   content only in the temporary `pliki-taty` directory. Nothing at the next
   start finishes or undoes the update.

#212 (`bez_opiekuna`: the guardian does not start, or the old Centrum never
releases the port) is fixed: Centrum rolls the clone back when
`restart_guardian.launch` raises, and the guardian rolls it back when the port
is not released, then shows the dialog.

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
shortcut start after a failure or a switch-off, and all eight kinds of new
version.

Assumed, and not checked:

- Each Git command, each `copy2` and the guardian are indivisible. A switch-off
  in the middle of `git merge` (a half-updated working tree) is not modelled.
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
