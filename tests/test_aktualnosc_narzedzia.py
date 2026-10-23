"""Źródła Aktualności narzędzia, których HTTP API Centrum nie dosięga, bo w testach są podstawione.

Lista tagów Wydań pochodzi z lokalnego serwera HTTP na 127.0.0.1, nigdy z GitHuba.
Commit narzędzia pochodzi z syntetycznych katalogów ``.git``.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import time

import pytest

from rozliczenia.centrum.tool_freshness import release_commit_from
from rozliczenia.centrum.version import tool_commit

MAIN = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"
BRANCH = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"
OLDER = "1111111111111111111111111111111111111111"
NEWEST = "2222222222222222222222222222222222222222"
OTHER = "3333333333333333333333333333333333333333"


def _tags(*named: tuple[str, str]) -> str:
    return json.dumps([{"name": name, "commit": {"sha": sha, "url": "https://api.github.com/x"}} for name, sha in named])


# Ścieżka wybiera odpowiedź API GitHuba na listę tagów: kolejność jak u GitHuba nie jest kolejnością Wydań.
_PAGES = {
    "/tagi": (_tags(("v0.9.0", OLDER), ("v0.10.0", NEWEST), ("proba", OTHER), ("v0.10", OTHER)), None),
    "/strona-1": (_tags(("v0.9.0", OLDER)), "/strona-2"),
    "/strona-2": (_tags(("v1.0.0", NEWEST), ("v0.11.0", OTHER)), None),
    "/bez-wydan": (_tags(("proba", OTHER)), None),
    "/bez-konca": (_tags(("v0.1.0", OLDER)), "/bez-konca"),
}


class _GitHub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in _PAGES:
            body, following = _PAGES[self.path]
            self.send_response(200)
            if following is not None:
                host = self.headers["Host"]
                self.send_header("Link", f'<http://{host}{following}>; rel="next", <http://{host}/tagi>; rel="last"')
            self.end_headers()
            self.wfile.write(body.encode("ascii"))
        elif self.path == "/limit":
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_najnowsze_wydanie_to_najwyzszy_numer_a_nie_ostatni_tag_alfabetycznie(github: str) -> None:
    assert release_commit_from(f"{github}/tagi", timeout_s=2) == NEWEST


def test_najnowsze_wydanie_ze_wszystkich_stron_listy_tagow(github: str) -> None:
    assert release_commit_from(f"{github}/strona-1", timeout_s=2) == NEWEST


@pytest.mark.parametrize(
    "path", ["/limit", "/strona", "/bez-wydan", "/bez-konca"], ids=["odmowa", "nie-lista", "bez-wydan", "bez-konca"]
)
def test_odmowa_odpowiedz_bez_wydania_albo_niepelna_lista_to_nie_wiadomo(github: str, path: str) -> None:
    assert release_commit_from(github + path, timeout_s=2) is None


def test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu() -> None:
    with socket.socket() as silent:  # przyjmuje połączenie i nigdy nie odpowiada
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        started = time.monotonic()

        commit = release_commit_from(f"http://127.0.0.1:{silent.getsockname()[1]}/tagi", timeout_s=0.3)

        assert (commit, time.monotonic() - started < 1.5) == (None, True)


def test_brak_sieci_to_nie_wiadomo() -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]  # port zwolniony po wyjściu: połączenie zostaje odrzucone

    assert release_commit_from(f"http://127.0.0.1:{port}/tagi", timeout_s=2) is None


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
