# Pomiar u taty

Centrum measures its own speed on Dad's computer without Dad seeing anything:
every API answer carries `Server-Timing` with the handling time only, and after
every ready view (the cold start of a page, a menu click) the browser sends one
measurement that the server appends to the Centrum log as a `pomiar` entry. The
entry holds the page id from the menu, the times in milliseconds, and for each
API request the operation name from the contract with the browser and server
time, so Maks can tell slow OneDrive reads from a slow browser. No address,
path, period token or content reaches the log.

## Sub-features

- `pomiar-zimny-start`: opening each of the four pages afresh logs `pomiar widok=zimny-start strona=<id>` with `gotowe_ms`, `fcp_ms`, `szkielet_ms`, and `zapytania` where every request is `<operation>:<browser ms>/<server ms>`.
- `pomiar-server-timing`: every API answer the browser got during those cold starts has `Server-Timing: centrum;dur=<ms>` and nothing more.
- `pomiar-przejscia-w-menu`: clicking Uruchomienia, Metryki, Konfiguracja, Okresy in the sidebar logs one `widok=przejscie-w-menu` entry per click, in order, without `fcp_ms`, each request with its server time.
- `pomiar-bez-sladu`: the page shows no alert, dialog or toast; the `pomiar` entries hold no path, `/api/` address or period token.
- `pomiar-obcy-origin`: a measurement from a foreign `Origin` is refused with 403 and adds no entry.

## How to get to it (user POV)

- None: Dad opens and clicks through Centrum as always. Maks reads the `pomiar` entries in `logs/centrum-rozliczen.log` on Dad's computer.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. The drive points Centrum to the fixture's folder okresów and Rejestr zleceń unless a feature before did (`ensure_files_set`), so Okresy and Uruchomienia read real synthetic files.

- **Cold start.** For each page id `okresy`, `uruchomienia`, `metryki`, `konfiguracja`: go to `about:blank`, then to `<url>#/<id>`; heading `<title>` (level 1) is visible. Within 10 s the log gains exactly one `pomiar` entry with `widok=zimny-start strona=<id>`, numeric `gotowe_ms`, `fcp_ms`, `szkielet_ms`, and `zapytania` matching `<operation>:<n>/<n>` for every request.
- **Server-Timing.** Every `/api/` response the page received during the cold starts (`page.on("response")`, `api/pomiar-server-timing.json`) has header `server-timing` matching `centrum;dur=<n>[.<n>]`.
- **Menu clicks.** Click links `Uruchomienia`, `Metryki`, `Konfiguracja`, `Okresy` (exact), waiting for each heading and 300 ms. The log gains four entries `widok=przejscie-w-menu` with `strona=` `uruchomienia`, `metryki`, `konfiguracja`, `okresy` in that order, none with `fcp_ms`, each with server times.
- **No trace.** No `alert` and no `dialog` on the page; capture `80`. `api/pomiar-dziennik.txt` holds every `pomiar` entry of the run; none contains the run root, `/api/` or a period token (`\d{2}_\d{2}_\d{2}_\d{4}`).
- **Foreign Origin.** `POST /api/view-timings` with `Origin: http://zly.example` and a valid body answers 403 (`api/pomiar-obcy-origin.json`); the log gains no `pomiar` entry.
- **Proof.** Screenshot `80`, `api/pomiar-*.{json,txt}`, `state/centrum-rozliczen.log`.

## Gotchas

- Playwright's `page.goto` to the same URL with another `#/<id>` changes only the hash, which Centrum counts as a menu click. Go to `about:blank` first for a real cold start.
- The browser sends the measurement after the next frame, so wait for the log entry before leaving the page; a navigation right after the heading appears can drop it.
- The measurement counts only requests finished before the content was ready; a refresh in the background that ends later is not in `zapytania`.
- This feature proves the measurement, not the speed: its times come from a busy verification run and are not compared with anything.
