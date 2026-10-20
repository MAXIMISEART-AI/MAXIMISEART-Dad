"""Źródła Aktualności narzędzia, których HTTP API Centrum nie dosięga, bo w testach są podstawione.

Commit `main` pochodzi z lokalnego serwera HTTP na 127.0.0.1, nigdy z GitHuba.
Commit narzędzia pochodzi z syntetycznych katalogów ``.git``.
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import threading
import time

import pytest

from rozliczenia.centrum.tool_freshness import main_commit_from
from rozliczenia.centrum.version import tool_commit

MAIN = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"
BRANCH = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"


class _GitHub(BaseHTTPRequestHandler):
    """Odpowiedź API GitHuba na commit `main` w postaci samego SHA; ścieżka wybiera wariant odpowiedzi."""

    def do_GET(self) -> None:
        if self.path == "/sha" and self.headers["Accept"] == "application/vnd.github.sha":
            self._answer(200, MAIN)
        elif self.path == "/limit":
            self._answer(403, '{"message": "API rate limit exceeded"}')
        else:
            self._answer(200, "<html>to nie jest commit</html>")

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


def test_commit_main_z_odpowiedzi_githuba(github: str) -> None:
    assert main_commit_from(f"{github}/sha", timeout_s=2) == MAIN


@pytest.mark.parametrize("path", ["/limit", "/strona"], ids=["odmowa", "nie-commit"])
def test_odmowa_albo_odpowiedz_bez_commitu_to_nie_wiadomo(github: str, path: str) -> None:
    assert main_commit_from(github + path, timeout_s=2) is None


def test_milczacy_serwer_nie_wydluza_diagnozy_ponad_limit_czasu() -> None:
    with socket.socket() as silent:  # przyjmuje połączenie i nigdy nie odpowiada
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        started = time.monotonic()

        commit = main_commit_from(f"http://127.0.0.1:{silent.getsockname()[1]}/sha", timeout_s=0.3)

        assert (commit, time.monotonic() - started < 1.5) == (None, True)


def test_brak_sieci_to_nie_wiadomo() -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]  # port zwolniony po wyjściu: połączenie zostaje odrzucone

    assert main_commit_from(f"http://127.0.0.1:{port}/sha", timeout_s=2) is None


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
