---
name: verify-kolejka-skrzynki
description: Exhaustively check that the Kolejka Skrzynki Zgłoszeń (`Outbox` in `src/rozliczenia/centrum/outbox.py`) delivers every part of every wysyłka (Zgłoszenie, Kontrola ilości, Logi Uruchomienia, Uwaga taty) at least once, keeps one issue per problem and per period, and empties the queue, under every order of network failures, answers lost after the Skrzynka acted, file errors and a killed Centrum. Use when a change touches `_deliver*`, `_comment_all`, `_waiting`, `Outbox._drain`, `_send_all`, `_remove`, `resume` or the delivery marker in `outbox.py`, the box calls in `keyed_box.py` or `newest_with_line` in `report_box.py`, adds a new `Target`, or when `explore_outbox.py` fails.
pilnuje:
  - src/rozliczenia/centrum/outbox.py
  - src/rozliczenia/centrum/keyed_box.py
  - src/rozliczenia/centrum/report_box.py
ci: .agents/skills/verify-kolejka-skrzynki/scripts/explore_outbox.py
---

# Verify Kolejka Skrzynki Zgłoszeń

## What CI runs and what stays local

CI runs `explore_outbox.py` (the `ci:` key) in Mutation checks whenever a change touches this skill,
and `check_outbox_mutations.py` in full CI on `main` and nightly on `main` (`mutacje-nocne.yml`) after a
change of this skill's folder. Run them locally only to reproduce a red Mutation checks step or the
night's issue, or one `--scope` while you work on it. What stays with you on every change to the covered code is „Does the
change touch it?”: read each commit since the sync commit against the table, because a change that
adds a new way to the Skrzynka (a new `Target`, a second writer of queue files, a box call outside
`KeyedBox`) passes the check without being checked. Sorting a red run as „When the check fails” says
also stays with you.

## The promise

- **WSZYSTKIE_CZESCI**: once the Skrzynka answers again, every part of every
  wysyłka in the queue is in the Skrzynka, in an issue of its target. ADR 0015
  (decision 12) and the docstring of `outbox.py`: „Wysyłka jest co najmniej
  raz”. Harm: Maks never sees the rest of Logi Uruchomienia, a Kontrola ilości
  or a Zgłoszenie, and nobody knows it is missing, because the queue file is
  gone.
- **JEDNO_ISSUE**: one problem has one open Zgłoszenie, one period has one issue
  okresu, and one Uwaga taty opens one issue. Harm: Maks gets the same problem
  in several issues, and the Powiadomienie follows only one of them.
- **KOLEJKA_PUSTA**: once failures stop, no file without its delivery marker
  is left in the queue folder (`config/zgloszenia/kolejka/`): the `RETRY_S`
  wake that `_drain` arms runs the queue again until it is sent. Harm: a
  wysyłka waits until Centrum restarts or something new is sent, after the
  network came back. A delivered file whose removal failed may wait for the
  next start: it has its marker and is never sent again.
- **BEZ_WYJATKU**: no pass of the queue ends in an exception that `_drain` logs
  as `nieoczekiwany-wyjatek` „wysyłka do Skrzynki Zgłoszeń”.

## Does the change touch it?

The check runs the real `Outbox` and `KeyedBox`. Each row is one indivisible
step of this code that the checker can fail, lose or kill:

| Step in the checker | Code |
| --- | --- |
| a box read | `keyed_box.py` `KeyedBox.labelled_issues` and `find_issue` (`newest_with_line`), called by `_deliver_report`, `_deliver_to_period`, `_deliver_to_known` in `outbox.py` |
| a box write | `KeyedBox.open_issue` and `comment`, called by `_deliver_new_issue`, `_deliver_report`, `_deliver_to_period`, `_comment_all` |
| the delivery marker | `Outbox._send_all`: `replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))` in `suppress(OSError)` |
| the removal of a queue file | `Outbox._remove` (`path.unlink`, `_undeleted`) |
| a pass of the queue | `Outbox._drain` (`_claimed`, `_send_all`, `_released`), run only when the real `Outbox.send_in_background` starts the queue thread (called by `Outbox.post`, `Outbox.resume` and `Outbox._woken`); the checker replaces only `threading.Thread` in `outbox.py`, which hands it the target |
| the `RETRY_S` wake | `Outbox._drain`: `self._clock.after(RETRY_S, self._woken)` when `_stopped_on` is set and no wake is armed; the checker calls an armed wake when nothing else asked for a pass, and a restart drops it with its process |
| a restart of Centrum | a new `Outbox` and `KeyedBox` on the same folder, then `Outbox.resume` |

Covered files: `src/rozliczenia/centrum/outbox.py`,
`src/rozliczenia/centrum/keyed_box.py`, and in
`src/rozliczenia/centrum/report_box.py` `newest_with_line`, by which
`KeyedBox.find_issue` finds the issue of a Zgłoszenie or a period.

**Sync commit: `8122ab4c`** (2026-10-26, `main` after #478). At this commit the
checker was confirmed to describe the code above. To see whether it needs
another look:

```bash
git log --oneline 8122ab4c..HEAD -- src/rozliczenia/centrum/outbox.py src/rozliczenia/centrum/keyed_box.py src/rozliczenia/centrum/report_box.py
```

Read each listed commit against the table. A change matters when it adds,
removes or reorders a box call, changes what a retry does with an issue it
finds, changes when the marker is written or the file removed, changes which
failure stops a pass (`_waiting`), or adds a `Target`. A new `Target` also needs
a scope in `SCOPES` and a branch in `_check` in `explore_outbox.py`. Changes to
the text of a wysyłka, the log lines, `prepare`, `delivered`, `wait_delivered`
and the addresses file do not matter here. Move the sync commit forward only
after the checker matches the code at the new commit and the check and its
mutations pass there.

## Run

```bash
.venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/explore_outbox.py
```

On Windows use `py -3` instead of `.venv/bin/python`. In a worktree, create its
`.venv` first (`python3 tools/setup_worktree.py`). It needs nothing beyond the
repo's Python and takes about 30 to 80 s, depending on the machine. `--scope NAME` runs one scope, and
`--strict` counts known findings and accepted risks as violations too.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `KOLEJKA OK` | 0 | Every rule holds in every schedule. |
| `KOLEJKA OK, ZNANE USTALENIA: n, ZAAKCEPTOWANE RYZYKA: m` | 0 | Only the known findings and accepted risks below, each printed with its shortest counterexample. A count of zero is left out. |
| `KOLEJKA: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below. The counterexample is printed. |
| `KOLEJKA: ZNALEZISKO ZNIKNĘŁO (n)` | 1 | A known finding or accepted risk no longer happens. If a change fixed it, delete it from `KNOWN_FINDINGS` or `ACCEPTED_RISKS` and from this file. |

## How it works and what it covers

`explore_outbox.py` writes the wysyłki of a scope into a real queue folder in a
temporary directory with `Outbox.post`, then runs passes of the real queue
(`_drain`) in its own thread. Only the start of the queue thread is replaced:
the real `send_in_background` decides, from `_draining`, whether a thread
starts, and the checker runs the target of each started thread. Behind `KeyedBox` stands `MemoryBox`, GitHub's
issues, labels, bodies and comments in memory. Before each step in the table
the checker picks one option:

- a box read: it answers, the network fails (`Unreachable`), or the process dies;
- a box write: it is accepted, the network fails before the Skrzynka sees it,
  the Skrzynka accepts it and the answer is lost (`Unreachable` after the
  effect, as a timed-out POST to GitHub), or the process dies before it;
- the marker or the removal: it works, raises `OSError` (Windows, antivirus or
  OneDrive holding the file), or the process dies before it;
- when files are left and nothing asked for a pass: the `RETRY_S` wake fires,
  if the code armed one, or Centrum restarts. Without an armed wake, the queue
  may also stay as it is until the next start. When the wake or the start does
  not ask for a pass either, the schedule ends there, and the rules judge what
  is left.

Bounds in every scope: at most 2 network failures, 1 lost answer, 1 file error
and 1 killed or restarted Centrum. After the failures run out the queue gets
3 more passes to empty itself. The checker re-runs the code from scratch for
every schedule. A schedule that reaches a pass boundary already explored stops
there: the code is deterministic, and the state decides every future and how
its breaks are judged. The state is the Skrzynka, the queue files, the files
`_remove` could not delete, the faults so far and those left, the passes left
and the exceptions so far. `_state` in `explore_outbox.py` names what it leaves
out and why.

| Scope | Wysyłki |
| --- | --- |
| `zgloszenie` | one Zgłoszenie (`ReportIssue`) in one part, as every Zgłoszenie is in practice |
| `zgloszenie-w-czesciach` | one Zgłoszenie in three parts, which a longer body would make |
| `watek-okresu` | two Kontrole ilości to one issue okresu (`PeriodThread`), in two and one part |
| `nowe-issue` | one Uwaga taty (`NewIssue`) in two parts |
| `znane-issue` | a comment in two parts to the existing issue of an Uwaga taty (`KnownIssue`) |

Not covered: a key that is missing or refused (`NoKey`, `Refused`: the pass
stops, nothing is sent, and `KeyedBox` keeps a refusal for `REFUSED_KEPT_S`),
content the Skrzynka rejects (`Rejected`: the file waits for the next start,
and the same content would be rejected again), Maks closing or deleting an
issue (`Gone`, `closed="reuse"`), a part posted twice (after a lost comment
answer or a restart, accepted as at least once and not a rule here), a
delivered file with its marker that waits for the next start, two queues on one folder (`_claimed`), a
process killed in the middle of `replace_atomically` (it leaves a `.tmp` that
`resume` removes), `prepare` holding a wysyłka back, a queue thread running at
the same time as `post` or `wait_delivered` (the checker runs each thread to its
end), `on_delivered` (Sprawy taty), and
more wysyłki or failures than the bounds above.

## Known findings

1. **`zgloszenie-w-czesciach`, WSZYSTKIE_CZESCI: a retried Zgłoszenie loses
   its later parts.** A single network failure is enough:
   1. the pass asks for open Zgłoszenia with the odcisk line and finds none;
   2. `open_issue` opens issue #1 with part 1;
   3. `comment(#1, part 2)` gets `Unreachable`, so the pass stops (`brak-sieci`);
   4. after `RETRY_S` the next pass finds issue #1 by its line;
   5. `_deliver_report` returns `Delivered(found, ())`, the marker is written
      and the file removed.

   Parts 2 and 3 never reach the Skrzynka. The docstring of `ReportIssue` takes
   over a found Zgłoszenie „bez komentarza” on purpose, because it may be one
   that another computer or an earlier Zgłoszenie opened, but the docstring of
   `outbox.py` and ADR 0015 promise at least once. It is latent in practice:
   the body (`reports.py`) has 20 short log entries, so it fits in one part,
   and nothing is lost in scope `zgloszenie`. Nothing guards that, though: the
   body also carries every frame of the call trace (`call_trace.py`) and the
   Diagnoza checks, and a body longer than one comment (`COMMENT_LIMIT` minus
   2 000 characters) makes the finding real.

   The finding excuses WSZYSTKIE_CZESCI in this scope only after the faults
   that cause it (`_after_opened_issue`: a lost answer to `open_issue` or a
   fault at a `comment`). Parts missing after any other schedule, including one
   without faults, are a new violation.

A known finding lives in `KNOWN_FINDINGS` in `explore_outbox.py`, with the
faults after which it is excused. When a code change fixes it, the check ends
with `ZNALEZISKO ZNIKNĘŁO`: delete the entry there and here.

## Accepted risks

1. **`nowe-issue`, JEDNO_ISSUE: a second issue of an Uwaga taty after the
   connection broke.** The Skrzynka opens the issue, then the answer is lost or
   a comment fails, and the next pass opens a second issue with the whole Uwaga.
   ADR 0015 accepts it: „Wysyłka jest co najmniej raz: zerwane połączenie po
   utworzeniu issue może dać drugie issue”. The docstring of `outbox.py` accepts
   the same after a process killed after the Skrzynka took the wysyłka and
   before its marker was on disk. A `NewIssue` has no line to find its issue by.

   The risk excuses JEDNO_ISSUE only after those faults
   (`_connection_broke_after_issue`): a lost answer to `open_issue`, any fault
   at a `comment`, or a process killed at a `comment`, at the marker, or at the
   removal after the marker failed. A second issue after any other schedule is a
   new violation. That is how the check holds the delivery marker to its
   promise: a file whose marker is on disk is never sent again, also when
   `_remove` could not delete it, or the process died while removing it.

An accepted risk lives in `ACCEPTED_RISKS` in `explore_outbox.py` with the
decision it rests on and the faults after which it is accepted.

## When the check fails

Read the counterexample as a story. Each numbered line is one step: a box call
in the code's words (`open_issue`, `comment(#n, część k/n)`, `labelled_issues`),
what the Skrzynka did, a file step of `_send_all`, or a pass or restart. Then
sort it:

- **Real bug**: every step can happen at Dad's (a network that drops, a POST
  whose answer is lost, Windows holding a file, Centrum closed), and the end
  state breaks the rule as stated above. Report it with the story. Fix the
  product code only if the user asks. If the user accepts the risk instead,
  record the decision in an ADR and add an entry to `ACCEPTED_RISKS` naming it.
- **Modeling error**: a step the code cannot take or GitHub would not do, for
  example `MemoryBox` returning an issue with another label, or a failure at a
  step the table does not list. Fix `MemoryBox`, `Scheduler` or
  `_intercepted`, and say what was wrong.
- **BEZ_WYJATKU**: a pass raised. The printed type and message name the
  exception; find where `_send_all` lets it out.

Never shrink a bound, a scope or a rule to make a real counterexample go away.

## After changing the checker or an intended change to the queue

CI proves the check can still fail: the night on `main` runs
`.agents/skills/verify-kolejka-skrzynki/scripts/check_outbox_mutations.py`
after a change of this skill's folder. It applies each broken variant of
`outbox.py` to a temporary copy of the checkout (`tools/mutacje.py`) and must end
with `MUTACJE OK`. Each of these gives `KOLEJKA: NOWE NARUSZENIE`:

- a failed comment skipped;
- a found issue okresu missing part 1;
- an issue okresu opened without looking for it;
- a known issue missing part 1;
- a network failure that skips the file instead of stopping the pass;
- a Zgłoszenie that never posts its comments, with the network working;
- an Uwaga taty that opens two issues;
- no delivery marker;
- no `RETRY_S` wake after a pass that stopped;
- the queue file removed before its marker is written;
- a `RETRY_S` wake that does not ask for a pass (`_woken`);
- a start that does not ask for a pass (`resume`);
- a new wysyłka that does not ask for a pass (`post`);
- a pass that does not clear `_draining`, so later requests only set `_again`;
- `send_in_background` that never starts the queue thread.

The Zgłoszenie, Uwaga, marker and removal mutations break the same rule as a
known finding or an accepted risk, in a schedule those do not excuse. A mutation reported as `NIEAKTUALNA` no longer
matches `outbox.py`: rewrite its `anchor` and `replacement` against the new code
so that it breaks the same rule again.
