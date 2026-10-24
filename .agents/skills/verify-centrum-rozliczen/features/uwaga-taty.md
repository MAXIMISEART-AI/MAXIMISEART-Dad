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

The Uwaga can also be pinned to one Uruchomienie procesu from Centrum. Under
`Treść`, `Dotyczy` chooses `Ogólna` or `Do Uruchomienia`; the second shows a
radio list `Uruchomienie` of `GET /api/dad-notes/runs` (the newest Centrum
Uruchomienia with a run id, plus the one the dialog was opened from), each with
process, period, `podgląd` or `zapis`, date and result. The finished card on
Uruchomienia and each Historia row of a Centrum Uruchomienie with a run id have
the icon `Napisz do Maksa o tym Uruchomieniu`; it opens the same dialog with
`Do Uruchomienia` chosen and that Uruchomienie checked. The figure is the
server's draft with that `run_id`: its footer names the Uruchomienie and links
to the first comment of its Logi in the skrzynka (`[Logi Uruchomienia](<url>)`).
The figure shows a Markdown link as its text only, as GitHub shows it to Maks,
so Dad never sees the address. `config/uwagi-taty.json` keeps the pinned
`run_id`.

## Sub-features

- `uwaga-ikona`: on Okresy, Uruchomienia, Metryki and Konfiguracja the header has the button `Napisz do Maksa` left of the theme toggle, with the tooltip `Napisz do Maksa`.
- `uwaga-puste-okno`: the dialog `Napisz do Maksa` opens with the focus in `Tytuł` and `Dotyczy` on `Ogólna` with no list; `Tytuł` and `Treść (niekonieczna)` have `maxlength` 120 and 10000 from the contract; `Tytuł` has the placeholder `Np. Brakuje kolumny z kilometrami`; `Wyślij` is disabled, also for a Tytuł of spaces; the figure shows the placeholder `Tytuł` and the server's draft body of an empty Uwaga.
- `uwaga-dlugi-tekst`: on a 1366×768 screen a 120-character Tytuł of wide letters and a 400-character Treść without a space (a pasted link) wrap inside the dialog: the dialog, the form, both fields, the figure and `Wyślij` stay on screen and inside the dialog, and the dialog does not scroll sideways.
- `uwaga-szkic-po-bledzie`: while the draft request fails, `Wyślij` stays disabled, no `alert` and no error toast appear, and the draft is asked again without Dad typing; once it answers, `Wyślij` is enabled.
- `uwaga-bez-klucza`: without `config/zgloszenia-klucz.txt` Dad types a Tytuł and a two-line Treść; the figure's title and body equal `POST /api/dad-notes/draft` for that text; `Do Uruchomienia` checks nothing (alone, with no Centrum Uruchomienie yet, the list says `Nie ma jeszcze Uruchomień z Centrum.`) and keeps `Wyślij` disabled; back on `Ogólna`, `Wyślij` shows the `status` `Wyślę do Maksa, gdy będzie internet.` with no `alert` and no error toast; `config/zgloszenia/kolejka/` holds one file whose `target` is `new_issue` labelled `uwaga-taty` with that title and whose only part is that body; `config/uwagi-taty.json` has the title with `number` `null`; the log says `skrzynka-czeka etykieta=uwaga-taty okres=bez-okresu przyczyna=brak-klucza`; the skrzynka gets nothing.
- `uwaga-wyslana`: with the key written and a slow skrzynka, a new opening is empty; a second Uwaga with a Tytuł only shows the draft body with the version line alone; `Wyślij` is disabled with a Spinner while sending, then the `status` reads `Uwaga wysłana do Maksa.`; the skrzynka has both Uwagi as `uwaga-taty` issues, each with the title and body its figure showed (the waiting one went out in the same pass); the queue is empty; `config/uwagi-taty.json` has both issue numbers; the Centrum log holds neither the key nor the text of an Uwaga.
- `uwaga-przycisk-na-karcie`: with the key still written, a `Podgląd bez zapisu` of Przebieg rozliczeń for the fixture's `needs_check` period through the UI finishes `Podgląd wymaga sprawdzenia`; the finished card has `Napisz do Maksa o tym Uruchomieniu` right of `Nowe Uruchomienie procesu`, with that tooltip; the preview's Logi reach the `logi-uruchomienia` issue of the file skrzynka.
- `uwaga-z-karty`: the card's button opens a new, empty Uwaga with `Do Uruchomienia` pressed and the radio list equal to `GET /api/dad-notes/runs?selected=<run id>` in order (process, period, `podgląd`, date, result), exactly the preview checked; the whole dialog fits the window: the list scrolls by itself past four and a half rows (up to four rows it is as tall as its rows), gives up height down to one row on a low window, and only then does the dialog scroll; `Wyślij` is disabled without a Tytuł.
- `uwaga-przypieta`: with a Tytuł and a Treść the figure equals `POST /api/dad-notes/draft` with that `run_id`, links shown as text: `Uruchomienie: Przebieg rozliczeń · <period> · podgląd · do sprawdzenia · <date> · wersja narzędzia …` and `[Logi Uruchomienia](<url>)` with the address of the first comment of the preview's Logi in the file skrzynka; the figure shows that line as `Logi Uruchomienia`, with no address anywhere in it.
- `uwaga-ogolna-i-z-powrotem`: `Ogólna` hides the list and the figure turns into the general draft ending `Uwaga ogólna · wersja narzędzia …` with no Logi; `Do Uruchomienia` again shows the same list with the preview still checked and the pinned figure.
- `uwaga-przypieta-wyslana`: `Wyślij` reads `Uwaga wysłana do Maksa.` with no error toast; the skrzynka has one new `uwaga-taty` issue with exactly the title and body of the figure's draft, whose `[Logi Uruchomienia](<url>)` link is that first comment's address; `config/uwagi-taty.json` keeps its number and the preview's `run_id`.
- `uwaga-z-historii`: in Uruchomienia, tab Historia, every row (all pages) has the button exactly when its Uruchomienie has a run id in `/api/metrics`; the oldest such row opens the dialog with `Do Uruchomienia`, the list of `GET /api/dad-notes/runs?selected=<its run id>` (in `all` it is older than the newest six, so the server adds it) and that row checked; at a laptop viewport of 1280×720 the same dialog shows the checked row (scrolled into the list's view) and `Wyślij` wholly on screen, with the dialog itself not scrolled.
- `uwaga-spoza-historii`: a preview whose metrics record could not be written (the metrics file of Przebieg rozliczeń read-only, as when OneDrive or another program holds it) still finishes with the card's button; the server's list leaves it out, so the dialog opens on `Do Uruchomienia` with the other Uruchomienia, none checked, `Wyślij` disabled even with a Tytuł, and above the list the sentence `Tego Uruchomienia nie ma w historii Centrum. Wybierz inne albo wyślij Uwagę ogólną.`; checking another row keeps the sentence above the list, and the figure pins the Uwaga to that row.

## How to get to it (user POV)

- Any page: the header icon `Napisz do Maksa` (a speech bubble with a plus), left of the theme toggle.
- Uruchomienia, the card of a finished Uruchomienie: the same icon `Napisz do Maksa o tym Uruchomieniu` right of `Nowe Uruchomienie procesu`.
- Uruchomienia, tab Historia (the same table as on Metryki): the icon in the last column of each row of a Centrum Uruchomienie with a run id.
- After `Wyślij`: the answer replaces the form in the same dialog; `Zamknij` (or the corner button, or Escape) closes it, and the next opening starts empty.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, with the file skrzynka `<root>/skrzynka-zgloszen/` (see `serve_centrum.py`). The skrzynka queue `config/zgloszenia/kolejka/` is empty: in `all`, `kontrola-ilosci` emptied it. The drive removes `config/zgloszenia-klucz.txt` first and at the end.

- **Ikona.** For each page in `PAGES` go to `#/<id>`, wait for its heading, and compare the bounding boxes of button `Napisz do Maksa` (exact) and the button whose name starts with `Włącz motyw`. Hover the icon: the text `Napisz do Maksa` appears (the button itself has only its `aria-label`). Capture `170`, plus the header close-up `170b` (not required).
- **Puste okno.** Click `Napisz do Maksa`: `dialog` `Napisz do Maksa`, `textbox` `Tytuł` focused, `button` `Wyślij` disabled. The drive posts `{"title": "", "body": ""}` to `/api/dad-notes/draft` (`api/uwaga-szkic-pusty.json`); the figure `Co dostanie Maks` shows `Tytuł` in its first `p` and that body in its second. Fill `Tytuł` with spaces: `Wyślij` stays disabled. Capture `171`.
- **Długi tekst.** Set the viewport to 1366×768. Fill `Tytuł` with 120 `W` and `Treść (niekonieczna)` with 400 characters without a space, wait until the figure equals `api/uwaga-szkic-dlugi.json`, then compare bounding boxes: the dialog lies within the viewport, the `form`, both textboxes, the figure and `Wyślij` within the dialog horizontally and within the viewport, and the dialog's `scrollWidth` is not above its `clientWidth`. Capture `172`. Restore the viewport and empty both fields.
- **Szkic po błędzie.** Abort every request to `/api/dad-notes/draft` (`page.route`), fill the synthetic Uwaga, and wait for a second aborted request; `Wyślij` is disabled, no `alert`, no error toast. Remove the route: `Wyślij` becomes enabled without another keystroke.
- **Bez klucza.** Fill `Tytuł` and `Treść (niekonieczna)` with the synthetic Uwaga, post the same text to `/api/dad-notes/draft` (`api/uwaga-szkic-pierwsza.json`) and wait until the figure shows exactly that title and body. Capture `173`. Click `Wyślij`: `status` in the dialog has the waiting sentence; no `alert`, no error toast. Capture `174`. Read the queue file, `config/uwagi-taty.json`, and the log. Click the first `Zamknij`.
- **Wysłana.** Write the synthetic key and `1500` to `pacing/skrzynka-ms.txt`. Open the dialog again: both fields empty. Fill only `Tytuł`, check the figure against `api/uwaga-szkic-druga.json`, click `Wyślij`: while the skrzynka is slow the button is disabled and named `Trwa Wyślij` (its Spinner's label comes first); capture `175` live. The `status` reads `Uwaga wysłana do Maksa.`; capture `176`. `api/uwaga-skrzynka.json` holds number, title, body and labels of the two `uwaga-taty` issues. Remove the pacing file, close the dialog, remove the key.
- **Przycisk na karcie.** Keep the key. `ensure_files_set`, go to `#/uruchomienia` (click `Nowe Uruchomienie procesu` when the current Uruchomienie is finished), radio `Przebieg rozliczeń`, `Podgląd bez zapisu`; `finished_result` keeps `api/uwaga-podglad.json` with the run id. In the region `Podgląd na żywo` the button `Napisz do Maksa o tym Uruchomieniu` (exact) is right of `Nowe Uruchomienie procesu`; hover it for the tooltip. Wait until a `logi-uruchomienia` issue of `<root>/skrzynka-zgloszen/` has a comment with `- Uruchomienie: <run id>,`; its address is `<issue file URI>#komentarz-<n>`. The drive switches to the light theme for `190`–`195` and back afterwards. Capture `190`.
- **Z karty.** Click the button: `dialog` `Napisz do Maksa`, empty `Tytuł`, in `group` `Dotyczy` the `button` `Do Uruchomienia` has `aria-pressed="true"`; `radiogroup` `Uruchomienie` has one `label` per entry of `api/uwaga-uruchomienia-z-karty.json` and `aria-checked="true"` only on the preview. Capture `191` (viewport).
- **Przypięta.** Fill `PINNED`, post it with `run_id` (`api/uwaga-szkic-przypieta.json`) and wait for the figure to equal it, each Markdown link `[text](url)` of the draft body replaced by its text. Capture `192`. Click `Ogólna`: no `radiogroup`, figure equals `api/uwaga-szkic-ogolna-z-karty.json`; capture `193`. Click `Do Uruchomienia`: the list and the check come back, the figure equals the pinned draft again.
- **Wysłana.** Click `Wyślij`, wait for the `status` `Uwaga wysłana do Maksa.`; `api/uwaga-przypieta-skrzynka.json` holds the new issue; check `config/uwagi-taty.json`. Click the first `Zamknij`.
- **Historia.** Click tab `Historia`, click `Pokaż starsze` until it is gone, compare the button count of each row with `run_id` of `/api/metrics` (`api/uwaga-historia.json`) sorted newest first. Hover the button of the oldest row with a run id, capture `194`, click it and check the dialog as in Z karty against `api/uwaga-uruchomienia-z-historii.json`. Capture `195`, press Escape. Set the viewport to 1280×720, click the same button and check the dialog again (`api/uwaga-uruchomienia-laptop.json`): the dialog's `scrollTop` is 0, and the checked row's `label` and `Wyślij` each lie wholly within the viewport and within every ancestor whose `overflow-y` is not `visible` (the list, the dialog), so nothing clips them. Capture `196`, press Escape, restore the viewport.
- **Spoza historii.** In tab `Uruchomienie` start a new `Podgląd bez zapisu` of Przebieg rozliczeń with `fixture["metrics"]["settlement"]` read-only (`stat.S_IREAD`), restore its mode once the card is finished (`api/uwaga-podglad-bez-metryk.json`), and check the file is unchanged and the preview is not in `GET /api/dad-notes/runs?selected=<its run id>` (`api/uwaga-uruchomienia-spoza-historii.json`). Click the card's button: the sentence is visible above the `radiogroup`, whose rows equal that list with nothing checked; fill `PINNED`, `Wyślij` stays disabled. Capture `197` (viewport). Click the first radio: it is checked and the sentence stays, the figure equals the draft with that row's `run_id` (`api/uwaga-szkic-spoza-historii.json`) and `Wyślij` is enabled. Press Escape.
- **Proof.** Screenshots `170`–`176` and `190`–`197` (`173b`, the empty or unchecked list, is not required), `api/uwaga-*.json`, and the checks in `drive.txt`.

## Gotchas

- The figure lags the typed text by one draft request: wait until it equals the server's draft (`run.wait_for`), never read it right after `fill`.
- The figure is the draft body with each Markdown link shown as its text; compare it with the draft after the same replacement (`MARKDOWN_LINK` in the drive), and check the link itself in the draft and in the skrzynka issue.
- Two buttons in the answer view are named `Zamknij`: the answer's own button comes first, the dialog's corner `X` (sr-only `Zamknij`) after it.
- The `status` holds only the answer sentence; the `Zamknij` button is outside it.
- `Wyślij` waits for the skrzynka up to 5 s. The pacing applies to each issue, and with the key both the waiting Uwaga and the new one go out in one pass, so keep the pacing under 2.5 s or the answer turns into `waiting`.
- The Kontrola ilości and the Zgłoszenia of earlier features take skrzynka numbers too; find Uwagi by the label `uwaga-taty`, never by number.
- Uwagi in `config/uwagi-taty.json` hold only titles. The queue file holds the body until the skrzynka takes it, so keep only synthetic text in the drive.
- The pinned figure links the Logi only once the preview's Logi are delivered; with the key written before the preview they go out at its end, so wait for the comment before opening the dialog, otherwise the draft says `Logi Uruchomienia: w drodze (Uruchomienie <run id>)` and the sent issue gets the address at delivery instead.
- The radio rows have no value in the DOM; match them to the server's list by position and text (process, `<period> · <podgląd|zapis> · <date>` in Dad's time zone, result word) and read `aria-checked`.
- A dialog screenshot taken with `full_page` shows the page below the backdrop past the viewport; capture dialogs with `full_page=False`.
- The key would send later Kontrole ilości and Zgłoszenia at once, and `diagnoza` and `zgloszenie` start without it, so the drive removes it at the end.
- The laptop check bites only when the list is longer than about four rows: in `all` the oldest row is the seventh, alone with one Centrum Uruchomienie it is one row and the dialog fits anyway.
- A Centrum Uruchomienie missing from the history cannot be reached from Historia (its row is not there), only from the finished card. The drive makes the metrics write fail with a read-only file because `run_process` reports that failure to Dad as a warning and goes on; restore the mode in `finally`, or every later Uruchomienie of the run loses its record.
- `Wyślij` is disabled while `Tytuł` is empty, and a disabled button has `pointer-events: none`, so `document.elementFromPoint` passes it by; test visibility by boxes, not by hit testing.
