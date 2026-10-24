# Uwaga taty

From any view Dad clicks the header icon `Napisz do Maksa` and writes an
Uwaga taty ogólna: a required one-line `Tytuł` and an optional `Treść`. The
figure `Maks dostanie` shows exactly the issue Maks will get, as the server
composed it (`POST /api/dad-notes/draft`), with the tool version under the
text. `Wyślij` puts the Uwaga in the skrzynka queue as its own issue labelled
`uwaga-taty` and waits for the skrzynka up to 5 s: `Uwaga wysłana do Maksa.`
when it took the issue, otherwise the calm `Wyślę do Maksa, gdy będzie
internet.` with no Komunikat. A waiting Uwaga goes out with the next pass of
the queue. `config/uwagi-taty.json` keeps each Uwaga's title and, once sent,
its issue number.

## Sub-features

- `uwaga-ikona`: on Okresy, Uruchomienia, Metryki and Konfiguracja the header has the button `Napisz do Maksa` left of the theme toggle, with the tooltip `Napisz do Maksa`.
- `uwaga-puste-okno`: the dialog `Napisz do Maksa` opens with the focus in `Tytuł`; `Tytuł` and `Treść (niekonieczna)` have `maxlength` 120 and 10000 from the contract; `Tytuł` has the placeholder `Np. Brakuje kolumny z kilometrami`; `Wyślij` is disabled, also for a Tytuł of spaces; the figure shows the placeholder `Tytuł` and the server's draft body of an empty Uwaga.
- `uwaga-dlugi-tekst`: on a 1366×768 screen a 120-character Tytuł of wide letters and a 400-character Treść without a space (a pasted link) wrap inside the dialog: the dialog, the form, both fields, the figure and `Wyślij` stay on screen and inside the dialog, and the dialog does not scroll sideways.
- `uwaga-bez-klucza`: without `config/zgloszenia-klucz.txt` Dad types a Tytuł and a two-line Treść; the figure's title and body equal `POST /api/dad-notes/draft` for that text; `Wyślij` shows the `status` `Wyślę do Maksa, gdy będzie internet.` with no `alert` and no error toast; `config/zgloszenia/kolejka/` holds one file whose `target` is `new_issue` labelled `uwaga-taty` with that title and whose only part is that body; `config/uwagi-taty.json` has the title with `number` `null`; the log says `skrzynka-czeka etykieta=uwaga-taty okres=bez-okresu przyczyna=brak-klucza`; the skrzynka gets nothing.
- `uwaga-wyslana`: with the key written and a slow skrzynka, a new opening is empty; a second Uwaga with a Tytuł only shows the draft body with the version line alone; `Wyślij` is disabled with a Spinner while sending, then the `status` reads `Uwaga wysłana do Maksa.`; the skrzynka has both Uwagi as `uwaga-taty` issues, each with the title and body its figure showed (the waiting one went out in the same pass); the queue is empty; `config/uwagi-taty.json` has both issue numbers; the Centrum log holds neither the key nor the text of an Uwaga.

## How to get to it (user POV)

- Any page: the header icon `Napisz do Maksa` (a speech bubble with a plus), left of the theme toggle.
- After `Wyślij`: the answer replaces the form in the same dialog; `Zamknij` (or the corner button, or Escape) closes it, and the next opening starts empty.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, with the file skrzynka `<root>/skrzynka-zgloszen/` (see `serve_centrum.py`). The skrzynka queue `config/zgloszenia/kolejka/` is empty: in `all`, `kontrola-ilosci` emptied it. The drive removes `config/zgloszenia-klucz.txt` first and at the end.

- **Ikona.** For each page in `PAGES` go to `#/<id>`, wait for its heading, and compare the bounding boxes of button `Napisz do Maksa` (exact) and the button whose name starts with `Włącz motyw`. Hover the icon: the text `Napisz do Maksa` appears (the button itself has only its `aria-label`). Capture `170`, plus the header close-up `170b` (not required).
- **Puste okno.** Click `Napisz do Maksa`: `dialog` `Napisz do Maksa`, `textbox` `Tytuł` focused, `button` `Wyślij` disabled. The drive posts `{"title": "", "body": ""}` to `/api/dad-notes/draft` (`api/uwaga-szkic-pusty.json`); the figure `Co dostanie Maks` shows `Tytuł` in its first `p` and that body in its second. Fill `Tytuł` with spaces: `Wyślij` stays disabled. Capture `171`.
- **Długi tekst.** Set the viewport to 1366×768. Fill `Tytuł` with 120 `W` and `Treść (niekonieczna)` with 400 characters without a space, wait until the figure equals `api/uwaga-szkic-dlugi.json`, then compare bounding boxes: the dialog lies within the viewport, the `form`, both textboxes, the figure and `Wyślij` within the dialog horizontally and within the viewport, and the dialog's `scrollWidth` is not above its `clientWidth`. Capture `172`. Restore the viewport and empty both fields.
- **Bez klucza.** Fill `Tytuł` and `Treść (niekonieczna)` with the synthetic Uwaga, post the same text to `/api/dad-notes/draft` (`api/uwaga-szkic-pierwsza.json`) and wait until the figure shows exactly that title and body. Capture `173`. Click `Wyślij`: `status` in the dialog has the waiting sentence; no `alert`, no error toast. Capture `174`. Read the queue file, `config/uwagi-taty.json`, and the log. Click the first `Zamknij`.
- **Wysłana.** Write the synthetic key and `1500` to `pacing/skrzynka-ms.txt`. Open the dialog again: both fields empty. Fill only `Tytuł`, check the figure against `api/uwaga-szkic-druga.json`, click `Wyślij`: while the skrzynka is slow the button is disabled and named `Trwa Wyślij` (its Spinner's label comes first); capture `175` live. The `status` reads `Uwaga wysłana do Maksa.`; capture `176`. `api/uwaga-skrzynka.json` holds number, title, body and labels of the two `uwaga-taty` issues. Remove the pacing file, close the dialog, remove the key.
- **Proof.** Screenshots `170`–`176`, `api/uwaga-*.json`, and the checks in `drive.txt`.

## Gotchas

- The figure lags the typed text by one draft request: wait until it equals the server's draft (`run.wait_for`), never read it right after `fill`.
- Two buttons in the answer view are named `Zamknij`: the answer's own button comes first, the dialog's corner `X` (sr-only `Zamknij`) after it.
- The `status` holds only the answer sentence; the `Zamknij` button is outside it.
- `Wyślij` waits for the skrzynka up to 5 s. The pacing applies to each issue, and with the key both the waiting Uwaga and the new one go out in one pass, so keep the pacing under 2.5 s or the answer turns into `waiting`.
- The Kontrola ilości and the Zgłoszenia of earlier features take skrzynka numbers too; find Uwagi by the label `uwaga-taty`, never by number.
- Uwagi in `config/uwagi-taty.json` hold only titles. The queue file holds the body until the skrzynka takes it, so keep only synthetic text in the drive.
- The key would send later Kontrole ilości and Zgłoszenia at once, and `diagnoza` and `zgloszenie` start without it, so the drive removes it at the end.
