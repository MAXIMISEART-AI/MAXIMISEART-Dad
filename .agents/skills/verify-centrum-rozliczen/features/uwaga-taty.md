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
server's draft with that `run_id`: its footer names the Uruchomienie and leads
to the first comment of its Logi in the skrzynka (`Logi Uruchomienia: <url>`),
and `config/uwagi-taty.json` keeps the pinned `run_id`.

## Sub-features

- `uwaga-ikona`: on Okresy, Uruchomienia, Metryki and Konfiguracja the header has the button `Napisz do Maksa` left of the theme toggle, with the tooltip `Napisz do Maksa`.
- `uwaga-puste-okno`: the dialog `Napisz do Maksa` opens with the focus in `Tytuł` and `Dotyczy` on `Ogólna` with no list; `Tytuł` and `Treść (niekonieczna)` have `maxlength` 120 and 10000 from the contract; `Wyślij` is disabled, also for a Tytuł of spaces; the figure shows the placeholder `Tytuł` and the server's draft body of an empty Uwaga.
- `uwaga-bez-klucza`: without `config/zgloszenia-klucz.txt` Dad types a Tytuł and a two-line Treść; the figure's title and body equal `POST /api/dad-notes/draft` for that text; `Do Uruchomienia` checks nothing (alone, with no Centrum Uruchomienie yet, the list says `Nie ma jeszcze Uruchomień z Centrum.`) and keeps `Wyślij` disabled; back on `Ogólna`, `Wyślij` shows the `status` `Wyślę do Maksa, gdy będzie internet.` with no `alert` and no error toast; `config/zgloszenia/kolejka/` holds one file whose `target` is `new_issue` labelled `uwaga-taty` with that title and whose only part is that body; `config/uwagi-taty.json` has the title with `number` `null`; the log says `skrzynka-czeka etykieta=uwaga-taty okres=bez-okresu przyczyna=brak-klucza`; the skrzynka gets nothing.
- `uwaga-wyslana`: with the key written and a slow skrzynka, a new opening is empty; a second Uwaga with a Tytuł only shows the draft body with the version line alone; `Wyślij` is disabled with a Spinner while sending, then the `status` reads `Uwaga wysłana do Maksa.`; the skrzynka has both Uwagi as `uwaga-taty` issues, each with the title and body its figure showed (the waiting one went out in the same pass); the queue is empty; `config/uwagi-taty.json` has both issue numbers; the Centrum log holds neither the key nor the text of an Uwaga.
- `uwaga-przycisk-na-karcie`: with the key still written, a `Podgląd bez zapisu` of Przebieg rozliczeń for the fixture's `needs_check` period through the UI finishes `Podgląd wymaga sprawdzenia`; the finished card has `Napisz do Maksa o tym Uruchomieniu` right of `Nowe Uruchomienie procesu`, with that tooltip; the preview's Logi reach the `logi-uruchomienia` issue of the file skrzynka.
- `uwaga-z-karty`: the card's button opens a new, empty Uwaga with `Do Uruchomienia` pressed and the radio list equal to `GET /api/dad-notes/runs?selected=<run id>` in order (process, period, `podgląd`, date, result), exactly the preview checked; `Wyślij` is disabled without a Tytuł.
- `uwaga-przypieta`: with a Tytuł and a Treść the figure equals `POST /api/dad-notes/draft` with that `run_id`: `Uruchomienie: Przebieg rozliczeń · <period> · podgląd · do sprawdzenia · <date> · wersja narzędzia …` and `Logi Uruchomienia:` with the address of the first comment of the preview's Logi in the file skrzynka.
- `uwaga-ogolna-i-z-powrotem`: `Ogólna` hides the list and the figure turns into the general draft ending `Uwaga ogólna · wersja narzędzia …` with no Logi; `Do Uruchomienia` again shows the same list with the preview still checked and the pinned figure.
- `uwaga-przypieta-wyslana`: `Wyślij` reads `Uwaga wysłana do Maksa.` with no error toast; the skrzynka has one new `uwaga-taty` issue with exactly the figure's title and body, whose `Logi Uruchomienia:` line is that first comment's address; `config/uwagi-taty.json` keeps its number and the preview's `run_id`.
- `uwaga-z-historii`: in Uruchomienia, tab Historia, every row (all pages) has the button exactly when its Uruchomienie has a run id in `/api/metrics`; the oldest such row opens the dialog with `Do Uruchomienia`, the list of `GET /api/dad-notes/runs?selected=<its run id>` (in `all` it is older than the newest six, so the server adds it) and that row checked.

## How to get to it (user POV)

- Any page: the header icon `Napisz do Maksa` (a speech bubble with a plus), left of the theme toggle.
- Uruchomienia, the card of a finished Uruchomienie: the same icon `Napisz do Maksa o tym Uruchomieniu` right of `Nowe Uruchomienie procesu`.
- Uruchomienia, tab Historia (the same table as on Metryki): the icon in the last column of each row of a Centrum Uruchomienie with a run id.
- After `Wyślij`: the answer replaces the form in the same dialog; `Zamknij` (or the corner button, or Escape) closes it, and the next opening starts empty.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, with the file skrzynka `<root>/skrzynka-zgloszen/` (see `serve_centrum.py`). The skrzynka queue `config/zgloszenia/kolejka/` is empty: in `all`, `kontrola-ilosci` emptied it. The drive removes `config/zgloszenia-klucz.txt` first and at the end.

- **Ikona.** For each page in `PAGES` go to `#/<id>`, wait for its heading, and compare the bounding boxes of button `Napisz do Maksa` (exact) and the button whose name starts with `Włącz motyw`. Hover the icon: the text `Napisz do Maksa` appears (the button itself has only its `aria-label`). Capture `160`, plus the header close-up `160b` (not required).
- **Puste okno.** Click `Napisz do Maksa`: `dialog` `Napisz do Maksa`, `textbox` `Tytuł` focused, `button` `Wyślij` disabled. The drive posts `{"title": "", "body": ""}` to `/api/dad-notes/draft` (`api/uwaga-szkic-pusty.json`); the figure `Co dostanie Maks` shows `Tytuł` in its first `p` and that body in its second. Fill `Tytuł` with spaces: `Wyślij` stays disabled. Capture `161`.
- **Bez klucza.** Fill `Tytuł` and `Treść (niekonieczna)` with the synthetic Uwaga, post the same text to `/api/dad-notes/draft` (`api/uwaga-szkic-pierwsza.json`) and wait until the figure shows exactly that title and body. Capture `162`. Click `Wyślij`: `status` in the dialog has the waiting sentence; no `alert`, no error toast. Capture `163`. Read the queue file, `config/uwagi-taty.json`, and the log. Click the first `Zamknij`.
- **Wysłana.** Write the synthetic key and `1500` to `pacing/skrzynka-ms.txt`. Open the dialog again: both fields empty. Fill only `Tytuł`, check the figure against `api/uwaga-szkic-druga.json`, click `Wyślij`: while the skrzynka is slow the button is disabled and named `Trwa Wyślij` (its Spinner's label comes first); capture `164` live. The `status` reads `Uwaga wysłana do Maksa.`; capture `165`. `api/uwaga-skrzynka.json` holds number, title, body and labels of the two `uwaga-taty` issues. Remove the pacing file, close the dialog, remove the key.
- **Przycisk na karcie.** Keep the key. `ensure_files_set`, go to `#/uruchomienia` (click `Nowe Uruchomienie procesu` when the current Uruchomienie is finished), radio `Przebieg rozliczeń`, `Podgląd bez zapisu`; `finished_result` keeps `api/uwaga-podglad.json` with the run id. In the region `Podgląd na żywo` the button `Napisz do Maksa o tym Uruchomieniu` (exact) is right of `Nowe Uruchomienie procesu`; hover it for the tooltip. Wait until a `logi-uruchomienia` issue of `<root>/skrzynka-zgloszen/` has a comment with `- Uruchomienie: <run id>,`; its address is `<issue file URI>#komentarz-<n>`. The drive switches to the light theme for `166`–`171` and back afterwards. Capture `166`.
- **Z karty.** Click the button: `dialog` `Napisz do Maksa`, empty `Tytuł`, in `group` `Dotyczy` the `button` `Do Uruchomienia` has `aria-pressed="true"`; `radiogroup` `Uruchomienie` has one `label` per entry of `api/uwaga-uruchomienia-z-karty.json` and `aria-checked="true"` only on the preview. Capture `167` (viewport).
- **Przypięta.** Fill `PINNED`, post it with `run_id` (`api/uwaga-szkic-przypieta.json`) and wait for the figure to equal it. Capture `168`. Click `Ogólna`: no `radiogroup`, figure equals `api/uwaga-szkic-ogolna-z-karty.json`; capture `169`. Click `Do Uruchomienia`: the list and the check come back, the figure equals the pinned draft again.
- **Wysłana.** Click `Wyślij`, wait for the `status` `Uwaga wysłana do Maksa.`; `api/uwaga-przypieta-skrzynka.json` holds the new issue; check `config/uwagi-taty.json`. Click the first `Zamknij`.
- **Historia.** Click tab `Historia`, click `Pokaż starsze` until it is gone, compare the button count of each row with `run_id` of `/api/metrics` (`api/uwaga-historia.json`) sorted newest first. Hover the button of the oldest row with a run id, capture `170`, click it and check the dialog as in Z karty against `api/uwaga-uruchomienia-z-historii.json`. Capture `171`, press Escape.
- **Proof.** Screenshots `160`–`171` (`162b`, the empty or unchecked list, is not required), `api/uwaga-*.json`, and the checks in `drive.txt`.

## Gotchas

- The figure lags the typed text by one draft request: wait until it equals the server's draft (`run.wait_for`), never read it right after `fill`.
- Two buttons in the answer view are named `Zamknij`: the answer's own button comes first, the dialog's corner `X` (sr-only `Zamknij`) after it.
- The `status` holds only the answer sentence; the `Zamknij` button is outside it.
- `Wyślij` waits for the skrzynka up to 5 s. The pacing applies to each issue, and with the key both the waiting Uwaga and the new one go out in one pass, so keep the pacing under 2.5 s or the answer turns into `waiting`.
- The Kontrola ilości and the Zgłoszenia of earlier features take skrzynka numbers too; find Uwagi by the label `uwaga-taty`, never by number.
- Uwagi in `config/uwagi-taty.json` hold only titles. The queue file holds the body until the skrzynka takes it, so keep only synthetic text in the drive.
- The pinned figure shows the Logi address only once the preview's Logi are delivered; with the key written before the preview they go out at its end, so wait for the comment before opening the dialog, otherwise the draft says `Logi Uruchomienia: w drodze (Uruchomienie <run id>)` and the sent issue gets the address at delivery instead.
- The radio rows have no value in the DOM; match them to the server's list by position and text (process, `<period> · <podgląd|zapis> · <date>` in Dad's time zone, result word) and read `aria-checked`.
- A dialog screenshot taken with `full_page` shows the page below the backdrop past the viewport; capture dialogs with `full_page=False`.
- The key would send later Kontrole ilości and Zgłoszenia at once, and `diagnoza` and `zgloszenie` start without it, so the drive removes it at the end.
