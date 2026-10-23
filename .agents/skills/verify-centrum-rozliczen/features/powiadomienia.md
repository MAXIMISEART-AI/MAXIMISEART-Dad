# Powiadomienia

The bell in the header, right of `Napisz do Maksa`, opens the view Powiadomienia
(`#/powiadomienia`), which has no sidebar entry. The view lists Dad's sent Uwagi
taty and Zgłoszenia, newest first, each with its colored tag (`Uwaga`,
`Zgłoszenie`) and state: `Wysłana do Maksa.`, `Wyślę do Maksa, gdy będzie
internet.`, `Rozwiązana. Będzie w następnej wersji.` (Maks closed the issue as
`completed`) or `Maks przeczytał.` (`not_planned`). A Zgłoszenie is named by its
„Co się stało”, without the code. Only Maks's states are new: they light a red
dot on the bell. Entering the view marks them read at once (the dot goes out),
and the rows that were new keep a small dot and a light background until Dad
leaves. Centrum asks the skrzynka Zgłoszeń about Dad's open cases at start and
at most once per 10 minutes of its clock, one question per kind of case (label);
no network passes silently with the last known state.

## Sub-features

- `powiadomienia-dzwonek`: on all four pages the bell sits right of `Napisz do Maksa`; `GET /api/notifications` has the sent Uwaga as `uwaga`, `wyslana`, not new, and the open Zgłoszenie of `zgloszenie` as `zgloszenie` named by its „Co się stało”; `unread` counts the new ones.
- `powiadomienia-zamkniete`: after Maks closes the Uwaga as `completed` and the Zgłoszenie as `not_planned`, 10 minutes later the bell is `Powiadomienia, są nowe`; Centrum asked at most once per label, and a second page within 10 minutes asks nothing.
- `powiadomienia-widok`: the bell opens the view in the same tab with no sidebar item current; the Uwaga row says `Rozwiązana. Będzie w następnej wersji.`, the Zgłoszenie row `Maks przeczytał.`, both with the mark `nowe` and `data-fresh="true"`; the bell is plain `Powiadomienia` at once, the server's `unread` is 0 and `config/powiadomienia.json` keeps the read ids; no alert, no error toast; both themes.
- `powiadomienia-po-wyjsciu`: after Okresy and back, no row has the mark `nowe`.
- `powiadomienia-brak-sieci`: without network, Maks closing another Uwaga changes nothing 10 minutes later: Centrum asks, the row still says `Wysłana do Maksa.`, the bell has no dot, and there is no alert.

## How to get to it (user POV)

- The bell icon `Powiadomienia` in the header of every page, right of `Napisz do Maksa`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK` by `serve_centrum.py`, with the file skrzynka `<root>/skrzynka-zgloszen/`, its question log `<root>/skrzynka-zgloszen-zapytania.jsonl` (one line with the `label` per question that includes closed issues), and the clock shift `<root>/zegar/przesuniecie-min.txt`. The drive needs the Zgłoszenia of `zgloszenie` and the two Uwagi of `uwaga-taty` in the skrzynka; run alone, it drives those first. It writes the synthetic key to `config/zgloszenia-klucz.txt` and removes it at the end.

- **Bell.** Shift the clock by 10 minutes. For each page `#/<id>`: reload, wait for its heading and network idle; button `Powiadomienia` (prefix) in `header` is visible right of button `Napisz do Maksa`. `GET /api/notifications` (`api/powiadomienia-wyslane.json`): the newest Uwaga is `{"kind": "uwaga", "state": "wyslana", "unread": false}`, the open Zgłoszenie has `what` equal to its issue title after `KOD: `; `unread` is the sum of `unread`. Screenshot `72`.
- **Closed.** Harness: in `<root>/skrzynka-zgloszen/<n>.json` set `state` `closed`, `state_reason` `completed` and `closed_at` for the newest Uwaga, and `not_planned` for the open Zgłoszenie, and shift the clock by 10 minutes. Enter Okresy: the bell's name is `Powiadomienia, są nowe`; the question log grew by at most two lines. Enter Uruchomienia: no new line. Screenshot `73` and the header close-up `73b`.
- **View.** Click the bell: heading `Powiadomienia`, URL ends with `#/powiadomienia`, the menu `Sekcje Centrum rozliczeń` has no `Powiadomienia` link and no `aria-current`. In list `Powiadomienia`, listitem `Uwaga: <title>` contains `Rozwiązana. Będzie w następnej wersji.` and listitem `Zgłoszenie: <Co się stało>` contains `Maks przeczytał.`; each has the label `nowe` and `data-fresh="true"`. The bell's name is `Powiadomienia`. `GET /api/notifications` (`api/powiadomienia-przeczytane.json`) reaches `unread` 0; `config/powiadomienia.json` has `schema_version` 1 and at least two ids. No `alert`, no error toast. Screenshot `74`; toggle the theme, the mark stays, screenshot `75`; toggle back.
- **After leaving.** Sidebar `Okresy`, then the bell: no label `nowe` in the list, the bell is plain `Powiadomienia`.
- **No network.** Create `<root>/skrzynka-zgloszen/brak-sieci`, close the older Uwaga (`completed`), shift the clock by 10 minutes, open `#/powiadomienia` afresh: the question log grew, the older Uwaga still says `Wysłana do Maksa.`, no `alert`, no error toast, the bell has no dot. Screenshot `76`. Remove `brak-sieci` (also in `finally`).
- **Proof.** Screenshots `72`–`76`, `api/powiadomienia-*.json`, the checks in `drive.txt`; the key is neither in the Centrum log nor in the page.

## Gotchas

- Every `GET /api/notifications`, from the tab or from `run.api`, may ask the skrzynka; count questions in the log, not requests.
- The tab reads Powiadomienia on start, on every page change and on focus; the 10-minute limit keeps these from asking again.
- The Zgłoszenie that `zgloszenie` closed has no `state_reason`; Centrum reads it as `completed`, so it may already be new when this feature starts.
- Never point the app at the real GitHub skrzynka; the key is synthetic.
