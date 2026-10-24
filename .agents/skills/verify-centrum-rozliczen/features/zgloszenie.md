# Zgłoszenie

Under the Diagnoza of a stop „do Maksa” (or a repeated stop) Dad sees the
collapsed `Co zostanie wysłane` with the exact Zgłoszenie and `Wyślij do
Maksa`. One click, without a confirmation dialog, sends the Zgłoszenie to the
skrzynka Zgłoszeń (Maks's private repository on GitHub; here a directory).
Afterwards `Zgłoszenie wysłane do Maksa. Poczekaj na naprawę.` replaces the
button and stays after a reload. One problem has one open Zgłoszenie: the next
Uruchomienie with the same problem shows `Zgłoszenie tego problemu już jest
wysłane i czeka na naprawę.` instead of the button; once Maks closed it,
`Wyślij do Maksa` returns after the Diagnoza and the new Zgłoszenie links the
previous one. Without the key the Zgłoszenie waits in a Markdown file next to Dad's
settings with a three-part message and `Spróbuj ponownie`; a refused key
(`ZGLOSZENIE_ODMOWA`) and no network (`ZGLOSZENIE_BRAK_POLACZENIA`) save it the
same way with their own Komunikat, and when even the file cannot be written
(`ZGLOSZENIE_NIEZAPISANE`) Dad is told to copy the preview. Konfiguracja shows
whether the key is there, never its value.

## Sub-features

- `zgloszenie-podglad`: a stop „do Maksa” has `report` `ready`; `Diagnoza` finds no cause and shows `Wyślij do Maksa` with `Co zostanie wysłane`: title `BRAK_WZORCA: …`, the Komunikat code, period, mode, `- Logi: jeszcze niewysłane, Uruchomienie <run id>` (no key yet, so the Logi wait in the queue), tool commit, every check (with `Aktualność narzędzia`), no workbook row and no full path.
- `zgloszenie-bez-klucza`: without `config/zgloszenia-klucz.txt`, `Wyślij do Maksa` shows the `Ostrzeżenie` „Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń.” with `Spróbuj ponownie`; `config/zgloszenia/Zgłoszenie BRAK_WZORCA 08_14_09_2026.md` holds exactly the preview; the skrzynka stays empty.
- `zgloszenie-konfiguracja`: Konfiguracja reads `Zgłoszenia: brak klucza`, and after Maks writes the key (harness step) `Zgłoszenia: gotowe`; neither the answer nor the page holds the key.
- `zgloszenie-wyslane`: `Spróbuj ponownie` on Uruchomienia sends: status `Zgłoszenie wysłane do Maksa. Poczekaj na naprawę.`; the skrzynka has one issue labelled `zgloszenie`, equal to the preview; the unsent file is gone; `config/zgloszenia-wyslane.json` keeps the fingerprint and that issue's number (with the tool's commit, the „Co się stało”, the sending time and, once known, Maks's closing, which Powiadomienia read); the Centrum log has `zgloszenie-wyslane` and no key.
- `zgloszenie-po-odswiezeniu`: a reload shows the confirmation again (`report` `sent`).
- `zgloszenie-kolejne-uruchomienie`: a new Podgląd bez zapisu with the same stop shows `Zgłoszenie tego problemu już jest wysłane i czeka na naprawę.` at once (`report` `waiting`); after `Diagnoza` it stays, there is no `Wyślij do Maksa`, and the skrzynka still has one Zgłoszenie.
- `zgloszenie-zamkniete`: Maks closes that issue (harness step); the same stop again still shows the waiting `status` before the Diagnoza (the skrzynka's last answer in this Centrum); `Diagnoza` asks the skrzynka, the `status` goes, `Wyślij do Maksa` returns (`report` `ready`), and the preview has `- Poprzednie Zgłoszenie: #<its number>` and `- Logi: skrzynka-zgloszen/<n>.json#komentarz-<k>`, the comment of the Logi of this very Uruchomienie in its period's issue (the file skrzynka's address of a comment; GitHub's is the comment's URL).
- `zgloszenie-nowe-z-odnosnikiem`: `Wyślij do Maksa` shows the confirmation; the skrzynka has the first Zgłoszenie closed and a second one open, equal to the new preview; `config/zgloszenia-wyslane.json` has both numbers.
- `zgloszenie-inny-problem`: a stop without the Wzorzec pliku zbiorczego (same code, other three parts) has `report` `ready` and, after `Diagnoza`, `Wyślij do Maksa` next to the open second Zgłoszenie; nothing is sent.

## How to get to it (user POV)

- Uruchomienia: a stop with `Diagnoza`; after it, region `Diagnoza` holds `Wyślij do Maksa` and `Co zostanie wysłane`, or the confirmation, or the `Ostrzeżenie` with `Spróbuj ponownie`.
- Before a Diagnoza (after a reload or in a new Uruchomienie) only the confirmation, the waiting `status`, or the saved Zgłoszenie with `Spróbuj ponownie` is shown under the stop.
- Konfiguracja: the page header reads `Zgłoszenia: gotowe` or `Zgłoszenia: brak klucza`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, with the file skrzynka `<root>/skrzynka-zgloszen/` (see `serve_centrum.py`). Run alone, the drive points Centrum to the fixture's folder okresów and Rejestr zleceń itself. The drive removes `config/zgloszenia-klucz.txt` first and at the end.

- **Podgląd.** On `#/uruchomienia` (after `Nowe Uruchomienie procesu` when a result is shown) choose `Przygotowanie pliku zbiorczego` and `08_14_09_2026 · Brak plików okresu`, rename the Wzorzec rozliczenia wewnętrznego aside, click `Podgląd bez zapisu` (exact), rename it back after the stop. `GET /api/runs/current` has `stop_kind` `for_maks` and `report` `{"state": "ready"}`. Reload, click `Diagnoza` on the stop banner, then button `Co zostanie wysłane` in region `Diagnoza`. Figure `Treść Zgłoszenia` shows the title in its caption and the Markdown body in `pre`.
- **Bez klucza.** Click `Wyślij do Maksa`. Label `Ostrzeżenie` in region `Diagnoza` reads the message above and `plik Zgłoszenie BRAK_WZORCA 08_14_09_2026.md, folder zgloszenia`, with button `Spróbuj ponownie`. The file is `# <title>\n\n<body>` as shown.
- **Konfiguracja.** Link `Konfiguracja`: text `Zgłoszenia: brak klucza`. Write the synthetic key to `config/zgloszenia-klucz.txt` (harness: Maks's step), reload: `Zgłoszenia: gotowe`; `api/zgloszenie-konfiguracja.json` has `reports` `ready`.
- **Wysłane.** Link `Uruchomienia`, click `Spróbuj ponownie` in `Ostrzeżenie`. A `status` reads the confirmation; `api/zgloszenie-skrzynka.json` is the issue in the skrzynka.
- **Po odświeżeniu.** Reload: the same `status`.
- **Kolejne Uruchomienie.** Repeat the Podgląd step: the waiting `status` is there before any Diagnoza; after `Diagnoza` no `Wyślij do Maksa`.
- **Zamknięte.** Set `"state": "closed"` in `<root>/skrzynka-zgloszen/<number>.json` of the Zgłoszenie (Maks closing it). Repeat the Podgląd step, wait until no `*-logi-uruchomienia-<first 8 of run id>.json` is left in `config/zgloszenia/kolejka/` (the key is there, so the queue sends them), then `Diagnoza`: `Wyślij do Maksa` and `Co zostanie wysłane` with the link line. Click `Wyślij do Maksa`: the confirmation `status`; `api/zgloszenie-skrzynka-nowe.json` holds both issues.
- **Inny problem.** Repeat the Podgląd step with the Wzorzec pliku zbiorczego (`collective_template` in `fixture.json`) renamed aside instead, reload, `Diagnoza`: `Wyślij do Maksa`.
- **Proof.** Screenshots `60`–`66` and `68`–`71`, `api/zgloszenie-*.json`, and the checks in `drive.txt`.

## Gotchas

- Never point the app at the real GitHub skrzynka: `serve_centrum.py` injects the file skrzynka, and the key is synthetic.
- The preview belongs to the last Diagnoza of the Uruchomienie: a second `POST /api/runs/{id}/diagnosis` from the drive replaces it (its log tail differs), so compare the skrzynka with the preview shown in the tab, not with an extra API Diagnoza.
- Leaving and re-entering Uruchomienia drops the Diagnoza shown in the tab, but the server keeps the saved state and the Zgłoszenie, so `Spróbuj ponownie` still sends exactly the preview.
- Rename the Wzorzec back right after the stop: the Diagnoza must find no cause, and later features need the Wzorzec.
- Before a Diagnoza the waiting `status` comes from the skrzynka's last answer in this Centrum, or from the local sent state when this Centrum has not asked yet; the Centrum asks the skrzynka for the open Zgłoszenie of the problem in the Diagnoza and again when sending, so in this Centrum a closed Zgłoszenie shows only after `Diagnoza`. After a restart, once Powiadomienia have asked the skrzynka and written Maks's closing into the sent state, the same stop shows `report` `ready` before any Diagnoza.
- The file skrzynka finds the open Zgłoszenie by the `- Odcisk problemu:` line of an `open` file; edit only `state` when closing one.
- The Logi line is fixed when the Diagnoza runs, so the preview and the sent Zgłoszenie are the same text: Logi still in the queue at that moment stay `jeszcze niewysłane` in the Zgłoszenie even after they are sent. Wait for the queue before `Diagnoza` when the step needs the link.
- In `all`, the Kontrola ilości of features/kontrola-ilosci.md is the skrzynka's first issue, so the Zgłoszenia are not `1.json` and `2.json`. Find them by the label `zgloszenie` (`_issues`), never by number.
