---
name: verify-jedno-uruchomienie-naraz
description: Exhaustively check that Centrum rozliczeń runs one Uruchomienie procesu at a time and never closes during one (also while it waits for Dad's Decyzja), under every interleaving of two tabs, Dad and the server. Use when a change touches `RunHost` or `_Run` in `src/rozliczenia/centrum/runs.py`, `Shutdown` in `shutdown.py`, `stop_when_asked` in `server.py`, the `refuse_while` wiring in `app.py`, adds another action that must wait for a running Uruchomienie (such as Aktualizacja narzędzia), or `test_jedno_uruchomienie_naraz` fails.
---

# Verify jedno Uruchomienie naraz

## The promise

- **JEDNO_NARAZ**: Centrum never has two Uruchomienia procesu in progress at once.
  Harm: two engines work on the same Folder okresu and metrics file, and Dad gets
  two results that contradict each other.
- **BEZ_ZAMKNIECIA_W_TRAKCIE**: Centrum's server never ends while an Uruchomienie
  procesu is in progress, including one waiting for Dad's Decyzja. Harm: the
  Uruchomienie thread is a daemon, so the end of the Python process kills it
  mid-work. Dad saw it start and then gets no result; its metrics record and the
  end entry in the Centrum log are missing; a temporary folder can stay behind; a
  kill during publication is the [ADR 0005](../../../docs/adr/0005-przerwana-publikacja-plikow-okresu.md) case.

An Uruchomienie is in progress from the moment `RunHost.start` creates its `_Run`
until `RunHost.finished` has written its end to the Centrum log. The checker
tracks this itself, not through the code's `ended` flag.

## Does the change touch it?

| Covered code | What the check relies on |
| --- | --- |
| `runs.py` `RunHost.start`, `shutdown_refusal`, `decide`, `finished`, `publish` | check and claim of `_run` under `_lock`; refusal while a run has not ended |
| `runs.py` `_Run.work`, `confirm`, `answer` | when `ended` is set; waiting for the Decyzja on `_decided` |
| `shutdown.py` `Shutdown.request`, `wait`, `refuse_while` | refusal check, then `_requested.set()` |
| `app.py` `create_app`: `shutdown.refuse_while(runs.shutdown_refusal)` | the wiring the harness copies |
| `server.py` `serve.stop_when_asked` and uvicorn graceful shutdown | modelled by hand (see below) |

**Sync commit: `c81d155`.** At this commit the checker was confirmed to describe
the covered code (which last changed in `c041d3b`). To see whether it needs
another look:

```bash
git log --oneline c81d155..HEAD -- src/rozliczenia/centrum/runs.py src/rozliczenia/centrum/shutdown.py src/rozliczenia/centrum/server.py src/rozliczenia/centrum/app.py
```

For every listed commit, read its diff against the table. Move the sync commit
forward (here and in nothing else) only after you have confirmed that the
harness still matches the code at the new commit and the check and the mutations
pass there. Changes to process content, progress views, Diagnoza or Zgłoszenia
do not matter here: the checker replaces the engine with fixed steps.

## Run

```powershell
py -3 .agents\skills\verify-jedno-uruchomienie-naraz\scripts\explore_runs.py
```

On macOS or Linux use `.venv/bin/python` instead of `py -3`. It takes 10 to 13 s on a
Mac and runs in CI as `tests/test_jedno_uruchomienie_naraz.py`. In a worktree the
script checks the worktree's own `src`.

| Last line | Exit | Meaning |
| --- | --- | --- |
| `URUCHOMIENIA OK` | 0 | Both rules hold in every schedule. |
| `URUCHOMIENIA OK, ZNANE USTALENIA: n` | 0 | Only the known findings below, each printed with its counterexample. |
| `URUCHOMIENIA: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below, or a scope never reached a behaviour it must reach (`BRAK_ZAMKNIECIA`, `BRAK_ODMOWY_ZAMKNIECIA`, `BRAK_WYNIKU`, `BRAK_ODMOWY_STARTU`), so the check would prove nothing. |
| `URUCHOMIENIA: LUKA MODELU (n)` | 2 | `runs.py` or `shutdown.py` uses `threading` in a way the model does not cover (for example `RLock`, `Condition`, `wait(timeout=...)`). No verdict on the rules. |

`--scope zamknij-w-trakcie` or `--scope dwie-karty` runs one scope. `--strict`
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
Event is set. Schedules that reach a state already seen are cut short.

Replaced: `run_process` by an engine with one work step, an optional Decyzja
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

Not covered: Zatrzymania and errors inside the engine (`_Run.work`'s `except`
path), the CLI or a second Centrum process on another port, Windows logoff, the
SSE stream, `stopped`/`show_report`, more tabs or clicks than above, and
anything Aktualizacja narzędzia (PR #198) adds. When `RunHost.begin_update` or a
similar action that must not run during an Uruchomienie lands, add it as an actor
in `_drive` with a rule that it never overlaps an Uruchomienie or a shutdown, and
add a mutation for it.

## Known findings

Real defects in the current code, printed as `ZNANE USTALENIE` on every run.
Both break BEZ_ZAMKNIECIA_W_TRAKCIE:

1. **„Uruchom” between the refusal check and the accepted shutdown.**
   `Shutdown.request` calls `shutdown_refusal()` under `RunHost._lock`, releases
   it, logs, then sets `_requested`. Counterexample: Dad clicks „Zamknij” in
   tab A, and the server finds nothing in progress. Tab B's „Uruchom” enters
   `RunHost.start` and starts an Uruchomienie thread. Tab A sets `_requested`,
   and `stop_when_asked` ends the server with the Uruchomienie in progress.
2. **„Uruchom” after the shutdown was accepted.** `RunHost.start` does not know
   about the shutdown. A „Uruchom” that reaches the server before uvicorn stops
   accepting requests gets 200 and starts a thread that the end of the process
   kills.

A fix must cover both. One sketch passes the check: `shutdown_refusal` sets a
closing flag under `_lock` when it returns `None`, and `start` refuses with 409
while that flag is set. When a fix lands, run with `--strict`, then delete the
fixed entries from `KNOWN_FINDINGS` in `explore_runs.py` and from this list.

## When the check fails

Read the counterexample as a story. Each numbered line is one step:
`karta Uruchom n`, `karta Zamknij` and `tata` are browser requests,
`wątek Uruchomienie n` is the thread `RunHost.start` spawned, `serwer` is
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

Prove the check can still fail. This applies broken variants to a temporary copy
of `src`, never to the checkout, each in the one scope that catches it (about
50 s on a Mac, most of it `dwie-karty` for the split check and claim):

```powershell
py -3 .agents\skills\verify-jedno-uruchomienie-naraz\scripts\check_runs_mutations.py
```

It must end with `MUTACJE OK`. These all give `NOWE NARUSZENIE`: the check and
claim in `start` under two lock entries (two Uruchomienia at once), a refusal that
skips a run waiting for its Decyzja, `ended` set at the start of `_Run.work`, and
`Shutdown.request` without the refusal. `RLock` in `RunHost` gives `LUKA MODELU`.
CI runs this in the `mutations` job. A mutation reported as `NIEAKTUALNA` no longer matches its file.
Rewrite its `anchor` and `replacement` in `check_runs_mutations.py` so it breaks
the same rule again in the new code. Then move the sync commit forward as above.
