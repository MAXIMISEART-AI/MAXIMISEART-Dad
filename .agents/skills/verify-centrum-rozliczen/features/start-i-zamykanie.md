# Start i zamykanie Centrum

Dad starts Centrum from the desktop shortcut; a second click only opens the tab
of the Centrum already running, and a port held by another program gives a
three-part start message instead of a second server. Closing a browser tab
leaves Centrum running; only `Zamknij Centrum rozliczeń` in the sidebar stops
the server. Every start, recognised second start, start failure, shutdown and
stop leaves a safe line in the Centrum log (`logs/centrum-rozliczen.log`).

## Sub-features

- `start-gotowosc`: the served Centrum answers `health` with its identity and version, and the Centrum log starts with a `start` line naming the port.
- `start-druga-instancja`: the real launcher on the same port says `Centrum rozliczeń już działa`, opens only the tab, logs `juz-dziala`, and the first Centrum keeps serving.
- `start-obcy-program`: the real launcher on a port held by another program exits 1 with the three-part message and logs `blad-startu`.
- `zamykanie-karta`: closing a tab does not stop Centrum.
- `zamykanie-potwierdzenie`: `Zamknij Centrum rozliczeń` asks `Zamknąć Centrum rozliczeń?`; `Anuluj` leaves Centrum running.
- `zamykanie`: `Zamknij Centrum` shows `Centrum rozliczeń jest zamknięte`, the server process stops, and the log ends with `zamkniecie`, `stop`.

## How to get to it (user POV)

- The desktop shortcut „Centrum rozliczeń” (created by `Zainstaluj skrót Centrum rozliczeń.cmd`) starts Centrum without a console; clicking it again opens the tab.
- The sidebar footer button `Zamknij Centrum rozliczeń`, on every page.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. This feature closes it, so it runs last in `all`; nothing can be driven after it.
- The launcher steps copy the tool into `<root>/narzedzie` so the real launcher's log stays in the run root, and set `BROWSER` to a recorder that appends to `<root>/browser.txt`.

- **Readiness.** `GET /api/health` (`api/start-health.json`) names `centrum-rozliczen`; `<root>/logs/centrum-rozliczen.log` starts with `start … port=<port>`.
- **Second start.** Run `<root>/narzedzie/run_centrum.py --port <port>`. It exits 0, prints `Centrum rozliczeń już działa: <url>` (`api/start-druga-instancja.txt`), `browser.txt` holds exactly the URL, the copy's log holds `juz-dziala`, and `health` still answers.
- **Foreign program.** Bind a socket on a free port, then run the launcher on it. It exits 1, prints the lines `Co się stało`, `Gdzie`, `Co zrobić` with `zajmuje inny program`, nothing on stderr (`api/start-obcy-program.txt`), and the copy's log ends with `blad-startu`.
- **Tab close.** Open the URL in a second tab (`context.new_page()`), wait for heading `Okresy`, close it; `health` still answers.
- **Confirmation.** Click button `Zamknij Centrum rozliczeń` (exact). Alert dialog `Zamknąć Centrum rozliczeń?` shows `Wrócisz skrótem „Centrum rozliczeń” na pulpicie.`; capture `90`. Click `Anuluj`; the dialog closes and the log has no `zamkniecie`.
- **Close.** Click `Zamknij Centrum rozliczeń`, then `Zamknij Centrum`. Heading `Centrum rozliczeń jest zamknięte` appears, `health` stops answering, the log ends with `zamkniecie`, `stop`; capture `91`.
- **Proof.** Screenshots `90`–`91`, `api/start-*.txt`, `state/centrum-rozliczen.log`.

## Gotchas

- Run this feature last: after `zamykanie` the server is gone, and the runner's stop and cleanup report it as already stopped, which is expected.
- `--feature start-i-zamykanie` alone works on a fresh run; no settings are needed.
- The shortcut path (`pythonw`, no console) shows start messages in a native dialog that Playwright cannot click. This skill drives the console path of the same launcher; the windowless path is covered by `tests/test_centrum_launcher.py` (a simulated `pythonw` on macOS/Linux, the real `pythonw.exe` and the `.lnk` on Windows) and by hand.
- The foreign-program step waits up to 5 seconds: the launcher gives a program that accepts the connection but never answers `health` that long before deciding it is not Centrum.
- Name the buttons exactly: `Zamknij Centrum rozliczeń` (sidebar) and `Zamknij Centrum` (dialog) differ only by the last word.
