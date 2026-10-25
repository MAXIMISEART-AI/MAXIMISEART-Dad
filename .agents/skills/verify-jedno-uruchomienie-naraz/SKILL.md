---
name: verify-jedno-uruchomienie-naraz
description: Exhaustively check that Centrum rozliczeń runs one Uruchomienie procesu or Aktualizacja narzędzia at a time and never closes during one (also while it waits for Dad's Decyzja), under every interleaving of browser tabs, Dad and the server. Use when a change touches `RunHost` or `_Run` in `src/rozliczenia/centrum/runs.py`, `Shutdown` in `shutdown.py`, `stop_when_asked` in `server.py`, the `refuse_while` wiring in `app.py`, `ToolUpdates.start` or `_update` in `tool_updates.py`, adds another action that must wait for a running Uruchomienie, or `test_jedno_uruchomienie_naraz` fails.
pilnuje:
  - src/rozliczenia/centrum/runs.py
  - src/rozliczenia/centrum/shutdown.py
  - src/rozliczenia/centrum/server.py
  - src/rozliczenia/centrum/app.py
  - src/rozliczenia/centrum/tool_updates.py
ci: .agents/skills/verify-jedno-uruchomienie-naraz/scripts/explore_runs.py
---

# Verify jedno Uruchomienie naraz

## The promise

- **JEDNO_NARAZ**: Centrum never has two Uruchomienia procesu in progress at once,
  nor an Uruchomienie and an Aktualizacja narzędzia, nor two Aktualizacje. Harm: two
  engines work on the same Folder okresu and metrics file, and Dad gets two results
  that contradict each other; or Git and pip change the tool under a running engine.
- **BEZ_ZAMKNIECIA_W_TRAKCIE**: Centrum's server never ends while an Uruchomienie
  procesu is in progress, including one waiting for Dad's Decyzja. Harm: the
  Uruchomienie thread is a daemon, so the end of the Python process kills it
  mid-work. Dad saw it start and then gets no result; its metrics record and the
  end entry in the Centrum log are missing; a temporary folder can stay behind; a
  kill during publication is the [ADR 0005](../../../docs/adr/0005-przerwana-publikacja-plikow-okresu.md) case.
  The same holds for an Aktualizacja narzędzia until its restart guardian has
  started: killed mid-Git or mid-pip, it leaves the clone for the next start to
  roll back.
- **PO_WYNIKU_PRZED_KONCEM**: Centrum's server never ends between an
  Uruchomienie's result and its actions after the result (`RunHost.after`, the
  `after_run` list in `create_app`). Harm: the Logi Uruchomienia of every
  Uruchomienie and the Kontrola ilości of a Przebieg rozliczeń land in their files
  in those actions; a shutdown or update accepted in between kills the thread
  before the files exist, and Maks never gets them.

An Uruchomienie is in progress from the moment `RunHost.start` creates its `_Run`
until `RunHost.finished` has written its end to the Centrum log. The checker
tracks this itself, not through the code's `ended` flag. An Aktualizacja is in
progress from a successful `RunHost.begin_update` until `end_update` returns or,
after a new version, until the restart guardian has started and
`Shutdown.close_for_update` may end the server.

## Does the change touch it?

| Covered code | What the check relies on |
| --- | --- |
| `runs.py` `RunHost.start`, `shutdown_refusal`, `decide`, `finished`, `publish` | check and claim of `_run` under `_lock`; refusal while a run has not ended; an accepted shutdown sets `_closing` under the same lock; the start file (`run_started`, `run_cards.RunCards`) written outside the lock, after the claim and before the thread |
| `runs.py` `RunHost.begin_update`, `end_update`, `_busy_locked` | check and claim of `_updating` under `_lock`; refusal while closing, updating or running |
| `runs.py` `_Run.work`, `confirm`, `answer` | when `ended` is set; after-run actions (`RunHost.after`) before `finished`; waiting for the Decyzja on `_decided` |
| `shutdown.py` `Shutdown.request`, `wait`, `refuse_while`, `close_for_update` | refusal check, then `_requested.set()`; `close_for_update` sets it without the check |
| `tool_updates.py` `ToolUpdates.start`, `_update`, `_restart` | modelled by hand: `begin_update`, a log entry, the thread; then either `end_update` or the guardian and `close_for_update` |
| `app.py` `create_app`: `shutdown.refuse_while(runs.shutdown_refusal)` | the wiring the harness copies |
| `server.py` `serve.stop_when_asked` and uvicorn graceful shutdown | modelled by hand (see below) |

**Sync commit: `3ac432a`.** At this commit the checker was confirmed to describe
the covered code. To see whether it needs another look:

```bash
git log --oneline 3ac432a..HEAD -- src/rozliczenia/centrum/runs.py src/rozliczenia/centrum/shutdown.py src/rozliczenia/centrum/server.py src/rozliczenia/centrum/app.py src/rozliczenia/centrum/tool_updates.py
```

For every listed commit, read its diff against the table. Move the sync commit
forward (here and in nothing else) only after you have confirmed that the
harness still matches the code at the new commit and the check and the mutations
pass there. Changes to process content, progress views, Diagnoza or Zgłoszenia
do not matter here: the checker replaces the engine with fixed steps. Neither do
the actions after the result themselves (`after_run` in `app.py`): the checker
replaces them with one step, and their network work runs on a thread outside
`runs.py` that holds nothing. The same holds for the start-time retry of that
queue (`outbox.resume()` in `lifespan`).

## Run

```powershell
py -3 .agents\skills\verify-jedno-uruchomienie-naraz\scripts\explore_runs.py
```

On macOS or Linux use `.venv/bin/python` instead of `py -3`. It takes about 5 s on a
Mac and runs in CI as `tests/test_jedno_uruchomienie_naraz.py` and, whole, before this skill's
mutations (the `ci:` key). Run it locally only to reproduce a red CI step, or one
`--scope` while you work on it. In a worktree the script checks the worktree's own `src`.

| Last line | Exit | Meaning |
| --- | --- | --- |
| `URUCHOMIENIA OK` | 0 | All three rules hold in every schedule. |
| `URUCHOMIENIA OK, ZNANE USTALENIA: n` | 0 | Only the known findings below, each printed with its counterexample. |
| `URUCHOMIENIA: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below, or a scope never reached a behaviour it must reach (`BRAK_ZAMKNIECIA`, `BRAK_ODMOWY_ZAMKNIECIA`, `BRAK_WYNIKU`, `BRAK_ODMOWY_STARTU`), so the check would prove nothing. |
| `URUCHOMIENIA: LUKA MODELU (n)` | 2 | `runs.py` or `shutdown.py` uses `threading` in a way the model does not cover (for example `RLock`, `Condition`, `wait(timeout=...)`). No verdict on the rules. |

`--scope zamknij-w-trakcie`, `--scope dwie-karty` or `--scope aktualizacja` runs one scope. `--strict`
counts known findings as violations too: use it to confirm a fix.

## How it works and what it covers

The script runs the real `RunHost` and `Shutdown`, wired as in `create_app`, in
threads. FastAPI runs the sync handlers `startRun`, `decideRun` and `closeCentrum`
in a thread pool, so tabs really do run in parallel. Inside `runs.py` and
`shutdown.py`, `threading` is replaced by model primitives: entering
`RunHost._lock`, each `Event.set`/`clear`/`wait` and starting the Uruchomienie
thread is one indivisible step, as is each Centrum log entry and
`CentrumRuns.remember` (file writes in the real code). Before each step the
checker lets any thread whose step can go now go first, and it tries every such
order. A lock entry can go only while the lock is free, and `wait()` only once the
Event is set. The actions after the result (`AfterRun`) are one step that
writes nothing. Schedules that reach a state already seen are cut short.

Replaced: `ToolUpdates` by a „Zaktualizuj narzędzie” tab that calls the real
`begin_update`, logs and starts the update thread, and a thread whose Git, pip and
guardian work is one step ending either without a new version (or in a failure),
then `end_update`, or with the guardian started, then the real
`Shutdown.close_for_update`. Replaced: the last Uruchomienie before Centrum's start (`previous`) by none, and the start file (`run_started`)
by one step that writes nothing. Replaced: `run_process` by an engine with one work step, an optional Decyzja
through the real `_Run.confirm` (both variants are explored) and an end step. Every
Uruchomienie ends in success. Modelled by hand: after `Shutdown.wait()` returns,
the server may end at any moment when no HTTP request is in flight. This is
uvicorn's `should_exit` tick (≤ 0.1 s), during which new requests are still
accepted, followed by its graceful shutdown, which serves requests already
received.

| Scope | „Uruchom” tabs | „Zamknij Centrum rozliczeń” clicks | Dad's Decyzje |
| --- | --- | --- | --- |
| `zamknij-w-trakcie` | 1 | ≤ 2 (a refused click is retried) | ≤ 1 |
| `dwie-karty` | 2 | ≤ 1 | ≤ 2 |
| `aktualizacja` | 1, plus 2 „Zaktualizuj narzędzie” tabs | ≤ 1 | ≤ 1 |

Not covered: Zatrzymania and errors inside the engine (`_Run.work`'s `except`
path), `tools/uruchom_proces.py` or a second Centrum process on another port,
Windows logoff, the SSE stream, Diagnoza and Zgłoszenie (`diagnose`/`send_report`), more tabs or clicks than
above, and what Aktualizacja narzędzia does to the clone (the
[`verify-aktualizacja-narzedzia`](../verify-aktualizacja-narzedzia/SKILL.md) model
covers it). When another action that must not run during an Uruchomienie lands,
add it as an actor in `_drive` with a rule that it never overlaps an Uruchomienie
or a shutdown, and add a mutation for it.

## Known findings

None. The two earlier ones (a „Uruchom” between the refusal check and the
accepted shutdown, and a „Uruchom” after it) went away when `shutdown_refusal`
started closing `RunHost` to new Uruchomienia and Aktualizacje under its lock.
A finding the user accepts goes into `KNOWN_FINDINGS` in `explore_runs.py` and
here, with the printed signature and one line naming the decision.

## When the check fails

Read the counterexample as a story. Each numbered line is one step:
`karta Uruchom n`, `karta Zaktualizuj n`, `karta Zamknij` and `tata` are browser
requests, `wątek Uruchomienie n` is the thread `RunHost.start` spawned,
`wątek Aktualizacja n` the one `ToolUpdates.start` spawned, `serwer` is
`stop_when_asked`, and `[runs.py:LINE function]` is the code that took the step
(`[model]` marks a harness step). Then sort it into one of three cases:

- **Real bug**: the story can happen with two Centrum tabs on Dad's computer,
  and the end state breaks a rule as stated above. Report it with the story in
  those words. Fix the product code only if the user asks. If the user accepts
  it instead, add the printed signature to `KNOWN_FINDINGS` with one line naming
  the decision, and add it to Known findings here.
- **Modeling error**: the story contains a step the real system cannot take,
  such as a request arriving after uvicorn stopped accepting, or a thread
  passing a lock another thread holds. Fix the model primitives or the actors in
  `explore_runs.py`, then rerun the mutations below.
- **LUKA MODELU**: model the new `threading` use in `ModelThreading` with its
  real semantics (a step per entry or signal, and a step that can go only when
  it would not block), or ask whether the code should avoid it. Never reword a
  rule or shrink a scope to make a real counterexample disappear.

## After changing the checker or an intended change to the covered code

CI proves the check can still fail: Mutation checks runs the script below whenever a
change touches this skill. Run it locally only to reproduce a red Mutation checks step
or after you rewrite a mutation. It applies broken variants to a temporary copy
of `src`, never to the checkout, each in the one scope that catches it (about
45 s on a Mac):

```powershell
py -3 .agents\skills\verify-jedno-uruchomienie-naraz\scripts\check_runs_mutations.py
```

It must end with `MUTACJE OK`. These all give `NOWE NARUSZENIE`: the check and
claim in `start` under two lock entries (two Uruchomienia at once), a refusal that
skips a run waiting for its Decyzja, `ended` set at the start of `_Run.work`,
the actions after the result moved below `ended = True`,
`Shutdown.request` without the refusal, an accepted shutdown that does not set
`_closing`, `begin_update` without the closing or the running check, and `start`
without the updating check. `RLock` in `RunHost` gives `LUKA MODELU`.
CI runs this in the `mutations` job. A mutation reported as `NIEAKTUALNA` no longer matches its file.
Rewrite its `anchor` and `replacement` in `check_runs_mutations.py` so it breaks
the same rule again in the new code. Then move the sync commit forward as above.
