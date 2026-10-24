"""Klon narzędzia w testach: prawdziwy Git, lokalne repozytorium „origin” zamiast GitHuba.

``tool_repository`` buduje w katalogu testu repozytorium wydawcy (tu Maks
commituje nowe wersje), jego kopię bez katalogu roboczego jako „origin” i klon
narzędzia taty na pierwszym commicie. ``publish`` dodaje do `main` w „origin”
nowy commit i, jak Maks, wydaje go jako następne Wydanie (``released``);
``release`` robi to później. ``in_clone`` robi w klonie to, co mógłby zrobić ktoś przy
komputerze taty; ``state`` to wszystko, co aktualizacja mogłaby w klonie
zmienić. ``unreachable_origin`` i ``origin_asking_for_login`` to GitHub bez
internetu i GitHub, który prosi o logowanie, oba na tym komputerze. Żaden
pomocnik nie łączy się z siecią.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading

from rozliczenia.centrum.tool_freshness import GitHubReleases, PublishedRelease
from rozliczenia.centrum.tool_update import Release, newest_on_main

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Pliki pierwszej wersji narzędzia: śledzona konfiguracja wykonawców sprzed #161 i biblioteki.
FIRST_VERSION: Mapping[str, str] = {
    "pyproject.toml": '[project]\nname = "narzedzie"\nversion = "0.1.0"\n',
    "requirements.txt": "openpyxl>=3.1.5\n",
    "config/worker_mapping.yaml": "schema_version: 1\nworkers:\n  przyklad: Przykładowy Wykonawca\n",
    "config/worker_mapping.example.yaml": "schema_version: 1\nworkers:\n  przyklad: Przykładowy Wykonawca\n",
    "src/narzedzie.py": "WERSJA = 1\n",
}
# Wymagania nowej wersji: jedna biblioteka więcej.
NEW_REQUIREMENTS = "openpyxl>=3.1.5\nfastapi>=0.115\n"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "Maks Testowy",
    "GIT_AUTHOR_EMAIL": "maks@example.invalid",
    "GIT_COMMITTER_NAME": "Maks Testowy",
    "GIT_COMMITTER_EMAIL": "maks@example.invalid",
}


def isolated_git_environment() -> dict[str, str]:
    """Środowisko Gita testów z Maksem jako autorem commitów."""

    return os.environ | _IDENTITY


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        env=isolated_git_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}{result.stdout}"
    return result.stdout.strip()


def _succeeds(directory: Path, *args: str) -> bool:
    return subprocess.run(["git", "-C", str(directory), *args], env=isolated_git_environment(), check=False).returncode == 0


def _write(root: Path, files: Mapping[str, str | None]) -> None:
    for name, content in files.items():
        path = root / name
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


@dataclass(frozen=True)
class ToolRepository:
    publisher: Path
    origin: Path
    clone: Path

    def publish(
        self, files: Mapping[str, str | None], *, untrack: tuple[str, ...] = (), released: bool = True
    ) -> str:
        """Nowy commit na `main` w „origin”: ``files`` zmienia pliki (``None`` usuwa), ``untrack`` przestaje je śledzić.

        ``released=False`` to zmiana na `main`, która nie weszła do żadnego Wydania.
        """

        _write(self.publisher, files)
        if untrack:
            git(self.publisher, "rm", "--cached", "--quiet", *untrack)
        git(self.publisher, "add", "--all")
        git(self.publisher, "commit", "--quiet", "--message", "Nowa wersja narzędzia")
        git(self.publisher, "push", "--quiet", "origin", "main")
        if released:
            self.release()
        return git(self.publisher, "rev-parse", "HEAD")

    def release(self, commit: str = "HEAD", tag: str | None = None, *, annotated: bool = False) -> str:
        """Wydanie ``commit`` w „origin”: tag ``tag`` albo następny numer po najnowszym Wydaniu, z opisem albo bez."""

        name = tag or _next_release(git(self.publisher, "tag", "--list", "v*").split())
        git(self.publisher, "tag", *(["--annotate", "--message", f"Wydanie {name}"] if annotated else []), name, commit)
        git(self.publisher, "push", "--quiet", "origin", f"refs/tags/{name}")
        return name

    def github_releases(self) -> GitHubReleases:
        """Odpowiedź „origin” o najnowszym Wydaniu na `main`, wybranym jak w Centrum (``newest_on_main``)."""

        commits = {tag: git(self.origin, "rev-parse", f"{tag}^{{commit}}") for tag in git(self.origin, "tag").split()}

        def on_main(commit: str) -> bool:
            return _succeeds(self.origin, "merge-base", "--is-ancestor", commit, "main")

        newest = newest_on_main(commits, on_main)
        return GitHubReleases(newest.commit, None if newest.release is None else newest.release.tag)

    def published(self) -> tuple[PublishedRelease, ...]:
        """Opublikowane Wydania: tagi „origin” nie mają GitHub Release z notką."""

        return ()

    def head(self) -> str:
        return git(self.clone, "rev-parse", "HEAD")

    def in_clone(self, *args: str) -> str:
        return git(self.clone, *args)

    def read(self, name: str) -> str:
        return (self.clone / name).read_text(encoding="utf-8")

    def write(self, name: str, content: str) -> None:
        _write(self.clone, {name: content})

    def state(self) -> tuple[str, str, Mapping[str, str]]:
        """Commit, gałąź (albo ``HEAD`` bez gałęzi) i treść każdego pliku klonu poza ``.git``."""

        files = {
            path.relative_to(self.clone).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(self.clone.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(self.clone).parts
        }
        return self.head(), git(self.clone, "rev-parse", "--abbrev-ref", "HEAD"), files


def copy_centrum_runtime(destination: Path) -> Path:
    """Kopia narzędzia z Centrum i krokiem instalacji skrótu, bez ustawień i dziennika taty."""

    destination.mkdir(parents=True)
    for name in (
        "run_centrum.py",
        "install_centrum_shortcut.py",
        "pyproject.toml",
        ".gitignore",
    ):
        shutil.copy2(REPOSITORY_ROOT / name, destination)
    shutil.copytree(REPOSITORY_ROOT / "src", destination / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        REPOSITORY_ROOT / "config", destination / "config", ignore=shutil.ignore_patterns("centrum-ustawienia.yaml")
    )
    return destination


def tool_repository(directory: Path, files: Mapping[str, str] = FIRST_VERSION) -> ToolRepository:
    """Wydawca z pierwszą wersją ``files``, „origin” bez katalogu roboczego i klon taty na tym samym commicie."""

    publisher = directory / "wydawca"
    publisher.mkdir(parents=True)
    _write(publisher, files)
    return _published(directory, publisher)


def centrum_tool_repository(directory: Path, files: Mapping[str, str] | None = None) -> ToolRepository:
    """Jak ``tool_repository``, ale pierwsza wersja to prawdziwe Centrum rozliczeń (``copy_centrum_runtime``).

    ``files`` podmienia albo dodaje pliki tej pierwszej wersji.
    """

    publisher = copy_centrum_runtime(directory / "wydawca")
    _write(publisher, files or {})
    return _published(directory, publisher)


def _published(directory: Path, publisher: Path) -> ToolRepository:
    git(publisher, "init", "--quiet", "--initial-branch", "main")
    git(publisher, "add", "--all")
    git(publisher, "commit", "--quiet", "--message", "Pierwsza wersja narzędzia")
    origin = directory / "origin.git"
    git(directory, "clone", "--quiet", "--bare", str(publisher), str(origin))
    git(publisher, "remote", "add", "origin", str(origin))
    git(publisher, "tag", "v0.1.0")
    git(publisher, "push", "--quiet", "origin", "refs/tags/v0.1.0")
    clone = directory / "narzedzie"
    git(directory, "clone", "--quiet", str(origin), str(clone))
    return ToolRepository(publisher, origin, clone)


def _next_release(tags: list[str]) -> str:
    newest = max((release for tag in tags if (release := Release.of_tag(tag)) is not None), default=None)
    if newest is None:
        return "v0.1.0"
    major, minor, patch = newest.number
    return f"v{major}.{minor}.{patch + 1}"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def unreachable_origin() -> str:
    """Adres HTTP na tym komputerze, pod którym nikt nie słucha: jak GitHub bez internetu."""

    return f"http://127.0.0.1:{free_port()}/MAXIMISEART-Dad.git"


class _LoginRequired(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="GitHub"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def origin_asking_for_login() -> Iterator[str]:
    """Serwer HTTP na tym komputerze, który na każde pytanie Gita odpowiada „401: zaloguj się”, jak GitHub."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _LoginRequired)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/MAXIMISEART-Dad.git"
    finally:
        server.shutdown()
        server.server_close()


class FakeInstaller:
    """Instalator bibliotek w miejscu pip: zapamiętuje plik wymagań z jego treścią i kończy się ``succeeds``.

    ``hold`` zatrzymuje każdą instalację, dopóki test jej nie puści (``set``).
    """

    def __init__(self, *, succeeds: bool = True, hold: threading.Event | None = None) -> None:
        self.succeeds = succeeds
        self.hold = hold
        self.installed: list[tuple[Path, str]] = []

    def __call__(self, requirements: Path) -> bool:
        self.installed.append((requirements, requirements.read_text(encoding="utf-8")))
        if self.hold is not None:
            self.hold.wait()
        return self.succeeds


@contextmanager
def github_api_of(origin: Path) -> Iterator[str]:
    """API GitHuba (lista tagów i porównanie z `main`) dla repozytorium ``origin``, liczone Gitem w ``origin``.

    Adres zwrócony przez blok to repozytorium w tym API (``REPOSITORY_API``).
    """

    class _Api(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/repo/tags?per_page=100":
                tags = [
                    {"name": tag, "commit": {"sha": git(origin, "rev-parse", f"{tag}^{{commit}}")}}
                    for tag in git(origin, "tag").split()
                ]
                self._answer(json.dumps(tags))
            elif self.path.startswith("/repo/compare/") and self.path.endswith("...main?per_page=1&page=2"):
                commit = self.path.removeprefix("/repo/compare/").partition("...")[0]
                on_main = _succeeds(origin, "merge-base", "--is-ancestor", commit, "main")
                self._answer(json.dumps({"status": "ahead" if on_main else "diverged"}))
            else:
                self.send_response(404)
                self.end_headers()

        def _answer(self, body: str) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/repo"
    finally:
        server.shutdown()
        server.server_close()
