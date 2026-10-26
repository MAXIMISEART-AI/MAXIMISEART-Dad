"""Źródła Aktualności narzędzia i Powiadomienia o nowej wersji, których HTTP API Centrum nie dosięga, bo w testach są
podstawione.

Lista tagów Wydań i lista GitHub Releases pochodzą z lokalnego serwera HTTP na 127.0.0.1, nigdy z GitHuba.
Commit narzędzia pochodzi z syntetycznych katalogów ``.git``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import time

import pytest

from rozliczenia.centrum.tool_freshness import GitHubReleases, PublishedRelease, published_from, releases_from
from rozliczenia.centrum.tool_update import Release
from rozliczenia.centrum.version import tool_commit

MAIN = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"
BRANCH = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"
OLDER = "1111111111111111111111111111111111111111"
NEWEST = "2222222222222222222222222222222222222222"
OTHER = "3333333333333333333333333333333333333333"
OFF_MAIN = "4444444444444444444444444444444444444444"
NOT_COMPARED = "5555555555555555555555555555555555555555"
UNCOUNTED = "6666666666666666666666666666666666666666"
MERGED_BRANCH = "7777777777777777777777777777777777777777"
REFUSED_MIDWAY = "8888888888888888888888888888888888888888"
FIRST_COMMIT = "9999999999999999999999999999999999999999"
NOT_A_COMMIT = "nie-commit"
# Odpowiedź porównania commitu tagu z czubkiem `main` ``MAIN`` albo jego pierwszym rodzicem (``compare``); brak wpisu
# to odmowa GitHuba. ``OLDER`` jest pierwszym rodzicem ``MAIN``.
_STATUS = {
    (OLDER, MAIN): "ahead",
    (OLDER, f"{MAIN}~1"): "identical",
    (NEWEST, MAIN): "identical",
    (OTHER, MAIN): "diverged",
    (OFF_MAIN, MAIN): "behind",
    # Commit gałęzi wciągniętej merge'em: przodek `main`, ale nie jego pierwszego rodzica. Przy ``REFUSED_MIDWAY``
    # GitHub odmawia dopiero porównania z pierwszym rodzicem, czyli w połowie wyszukiwania.
    (MERGED_BRANCH, MAIN): "ahead",
    (MERGED_BRANCH, f"{MAIN}~1"): "behind",
    (REFUSED_MIDWAY, MAIN): "ahead",
    # Porównanie bez liczby commitów i porównanie z czubkiem `main`, który nie jest commitem: GitHub, który by je
    # dał, nie daje pełnej odpowiedzi.
    (UNCOUNTED, MAIN): "identical",
    (NEWEST, NOT_A_COMMIT): "identical",
    # Pierwszy commit repozytorium jest pierwszym rodzicem `main`, a `main` ma jeszcze dwa commity z wciągniętej
    # gałęzi (``ahead_by`` 3): ``MAIN~2`` i dalej nie istnieją (404).
    (FIRST_COMMIT, MAIN): "ahead",
    (FIRST_COMMIT, f"{MAIN}~1"): "identical",
}
_AHEAD_BY = {FIRST_COMMIT: 3}
_NOT_FOUND = {(FIRST_COMMIT, f"{MAIN}~2"), (FIRST_COMMIT, f"{MAIN}~3")}


def _tags(*named: tuple[str, str]) -> str:
    return json.dumps([{"name": name, "commit": {"sha": sha, "url": "https://api.github.com/x"}} for name, sha in named])


# Repozytorium (pierwszy człon ścieżki) wybiera listę tagów i jej strony; kolejność jak u GitHuba nie jest
# kolejnością Wydań.
_PAGES = {
    "/tagi/tags?per_page=100": (
        _tags(("v0.9.0", OLDER), ("v0.10.0", NEWEST), ("proba", OTHER), ("v0.10", OTHER), ("v1.0.0-rc1", OTHER)),
        None,
    ),
    "/strony/tags?per_page=100": (_tags(("v0.9.0", OLDER)), "/strony/tags?page=2"),
    "/strony/tags?page=2": (_tags(("v1.0.0", NEWEST), ("v0.11.0", OLDER)), None),
    "/spoza-main/tags?per_page=100": (_tags(("v0.2.0", OLDER), ("v0.3.0", OFF_MAIN), ("v0.4.0", OTHER)), None),
    "/tylko-spoza-main/tags?per_page=100": (_tags(("v0.3.0", OFF_MAIN)), None),
    "/bez-wydan/tags?per_page=100": (_tags(("proba", OTHER)), None),
    "/bez-konca/tags?per_page=100": (_tags(("v0.1.0", OLDER)), "/bez-konca/tags?per_page=100"),
    "/bez-porownania/tags?per_page=100": (_tags(("v0.1.0", NOT_COMPARED)), None),
    "/bez-czubka/tags?per_page=100": (_tags(("v0.1.0", NEWEST)), None),
    "/bez-czubka/git/ref/heads/main": (json.dumps({"object": {"sha": NOT_A_COMMIT}}), None),
    "/bez-liczby/tags?per_page=100": (_tags(("v0.1.0", UNCOUNTED)), None),
    "/z-galezi/tags?per_page=100": (_tags(("v0.1.0", MERGED_BRANCH)), None),
    "/odmowa-w-wyszukiwaniu/tags?per_page=100": (_tags(("v0.1.0", REFUSED_MIDWAY)), None),
    "/od-pierwszego-commitu/tags?per_page=100": (_tags(("v0.1.0", FIRST_COMMIT)), None),
}

NOTES = "Plik zbiorczy ma kolumnę z kilometrami.\n\n## Rozwiązane sprawy taty\n\n- Uwaga taty #12: Kilometry\n"


def _release(tag: object, *, body: object = "", published_at: object = "2026-10-20T10:00:00Z", **flags: object) -> object:
    return {"tag_name": tag, "body": body, "published_at": published_at, "draft": False, "prerelease": False} | flags


# Lista GitHub Releases: od najnowszego, z szkicem, wersją przedpremierową, tagiem, który nie jest Wydaniem, i
# wpisami w innym kształcie.
_PAGES["/wydania/releases?per_page=30"] = (
    json.dumps(
        [
            _release("v0.3.0", draft=True),
            _release("v0.2.1", prerelease=True),
            _release("v0.2.0", body=NOTES, published_at="2026-10-20T10:00:00Z"),
            _release("proba"),
            _release("v0.1.5", published_at="20.10.2026"),
            _release("v0.1.4", published_at="2026-10-15T10:00:00"),
            _release("v0.1.3", body=7),
            "v0.1.2",
            _release("v0.1.0", body=None, published_at="2026-10-01T08:00:00+02:00"),
        ]
    ),
    None,
)


class _GitHub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        repository, _, rest = self.path[1:].partition("/")
        if self.path in _PAGES:
            body, following = _PAGES[self.path]
            self.send_response(200)
            if following is not None:
                host = self.headers["Host"]
                self.send_header("Link", f'<http://{host}{following}>; rel="next", <http://{host}/tagi>; rel="last"')
            self.end_headers()
            self.wfile.write(body.encode("ascii"))
        elif rest == "git/ref/heads/main" and repository != "limit":
            self._answer(200, json.dumps({"ref": "refs/heads/main", "object": {"sha": MAIN, "type": "commit"}}))
        elif rest.startswith("compare/") and rest.endswith("?per_page=1&page=2"):
            base, _, head = rest.removeprefix("compare/").removesuffix("?per_page=1&page=2").partition("...")
            status = _STATUS.get((base, head))
            if (base, head) in _NOT_FOUND:
                self._answer(404, '{"message": "Not Found"}')
            elif status is None:
                self._answer(403, '{"message": "API rate limit exceeded"}')
            else:
                counted = {} if base == UNCOUNTED else {"ahead_by": _AHEAD_BY.get(base, 1)}
                self._answer(200, json.dumps({"status": status, **counted, "commits": [], "files": []}))
        elif repository == "limit":
            self._answer(403, '{"message": "API rate limit exceeded"}')
        else:
            self._answer(200, "<html>to nie jest lista tagów</html>")

    def _answer(self, status: int, body: str) -> None:
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body.encode("ascii"))

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def github() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitHub)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_najnowsze_wydanie_to_najwyzszy_numer_a_nie_ostatni_tag_alfabetycznie(github: str) -> None:
    assert releases_from(f"{github}/tagi", timeout_s=2) == GitHubReleases(NEWEST, "v0.10.0")


def test_najnowsze_wydanie_ze_wszystkich_stron_listy_tagow(github: str) -> None:
    assert releases_from(f"{github}/strony", timeout_s=2) == GitHubReleases(NEWEST, "v1.0.0")


def test_wyzsze_wydanie_spoza_main_jest_pominiete_a_nizsze_na_main_wybrane(github: str) -> None:
    assert releases_from(f"{github}/spoza-main", timeout_s=2) == GitHubReleases(OLDER, "v0.2.0")


@pytest.mark.parametrize("repository", ["bez-wydan", "tylko-spoza-main"])
def test_bez_wydania_na_main_github_odpowiada_ze_nie_ma_wydania(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=2) == GitHubReleases(None, None)


@pytest.mark.parametrize(
    "repository",
    ["limit", "strona", "bez-konca", "bez-porownania", "bez-czubka", "bez-liczby"],
    ids=["odmowa", "nie-lista", "bez-konca", "odmowa-porownania", "czubek-main-nie-commitem", "porownanie-bez-liczby"],
)
def test_odmowa_odpowiedz_nie_z_api_albo_niepelna_lista_to_nie_wiadomo(github: str, repository: str) -> None:
    assert releases_from(f"{github}/{repository}", timeout_s=2) is None


def test_wydanie_z_galezi_wciagnietej_mergem_nie_jest_na_main_i_ta_odpowiedz_zostaje_w_pamieci(github: str) -> None:
    known: dict[str, bool] = {}

    assert releases_from(f"{github}/z-galezi", timeout_s=2, known=known) == GitHubReleases(None, None)
    assert known == {MERGED_BRANCH: False}


def test_wydanie_na_pierwszym_commicie_repozytorium_jest_na_main(github: str) -> None:
    assert releases_from(f"{github}/od-pierwszego-commitu", timeout_s=2) == GitHubReleases(FIRST_COMMIT, "v0.1.0")


def test_odmowa_githuba_w_polowie_wyszukiwania_to_nie_wiadomo_i_nic_nie_zostaje_w_pamieci(github: str) -> None:
    known: dict[str, bool] = {}

    assert releases_from(f"{github}/odmowa-w-wyszukiwaniu", timeout_s=2, known=known) is None
    assert known == {}


def test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu() -> None:
    with socket.socket() as silent:  # przyjmuje połączenie i nigdy nie odpowiada
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        started = time.monotonic()

        answer = releases_from(f"http://127.0.0.1:{silent.getsockname()[1]}/tagi", timeout_s=0.3)

        assert (answer, time.monotonic() - started < 1.5) == (None, True)


def test_brak_sieci_to_nie_wiadomo() -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]  # port zwolniony po wyjściu: połączenie zostaje odrzucone

    assert releases_from(f"http://127.0.0.1:{port}/tagi", timeout_s=2) is None


def test_lista_wydan_ma_tylko_opublikowane_wydania_z_notka_i_czasem_publikacji(github: str) -> None:
    assert published_from(f"{github}/wydania", timeout_s=2) == (
        PublishedRelease(Release((0, 2, 0), "v0.2.0"), NOTES, datetime(2026, 10, 20, 10, tzinfo=timezone.utc)),
        PublishedRelease(Release((0, 1, 0), "v0.1.0"), "", datetime(2026, 10, 1, 6, tzinfo=timezone.utc)),
    )


@pytest.mark.parametrize("repository", ["limit", "strona"], ids=["odmowa", "nie-lista"])
def test_lista_wydan_bez_odpowiedzi_api_to_nie_wiadomo(github: str, repository: str) -> None:
    assert published_from(f"{github}/{repository}", timeout_s=2) is None


def test_lista_wydan_bez_sieci_to_nie_wiadomo() -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]

    assert published_from(f"http://127.0.0.1:{port}/wydania", timeout_s=2) is None


def _git(root: Path, head: str) -> Path:
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(head + "\n", encoding="utf-8")
    return git


def test_commit_galezi_klonu(tmp_path: Path) -> None:
    git = _git(tmp_path, "ref: refs/heads/main")
    (git / "refs" / "heads" / "main").write_text(BRANCH + "\n", encoding="utf-8")

    assert tool_commit(tmp_path) == BRANCH


def test_commit_galezi_spakowanej(tmp_path: Path) -> None:
    git = _git(tmp_path, "ref: refs/heads/main")
    (git / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n{MAIN} refs/heads/inna\n{BRANCH} refs/heads/main\n",
        encoding="utf-8",
    )

    assert tool_commit(tmp_path) == BRANCH


def test_commit_odlaczonego_head(tmp_path: Path) -> None:
    _git(tmp_path, BRANCH)

    assert tool_commit(tmp_path) == BRANCH


def test_commit_katalogu_roboczego_worktree(tmp_path: Path) -> None:
    clone = tmp_path / "klon"
    git = _git(clone, "ref: refs/heads/main")
    (git / "refs" / "heads" / "zgloszenia").write_text(BRANCH + "\n", encoding="utf-8")
    worktree_git = git / "worktrees" / "drugi"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/zgloszenia\n", encoding="utf-8")
    (worktree_git / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "drugi"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")

    assert tool_commit(worktree) == BRANCH


@pytest.mark.parametrize(
    "head",
    [None, "ref: refs/heads/brak", "nie-commit"],
    ids=["bez-gita", "galaz-bez-commitu", "uszkodzony-head"],
)
def test_narzedzie_bez_commitu(tmp_path: Path, head: str | None) -> None:
    if head is not None:
        _git(tmp_path, head)

    assert tool_commit(tmp_path) is None
