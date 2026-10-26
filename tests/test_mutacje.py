"""``tools/mutacje.py`` dowodzi, że polecenie pada na zepsutym kodzie, bez dotykania checkoutu.

Mutacje dopisują kod na końcu modułów ``rozliczenia`` w kopii checkoutu; kotwicą jest cała treść
modułu, więc test nie zależy od niej.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

from tests.fixtures.git_repo import commit, git, repository
from tests.fixtures.potomne import beating

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "mutacje.py"
PACKAGE = "src/rozliczenia/__init__.py"
IMPORT = ("-c", "import rozliczenia")


def _appended(module: str, code: str) -> list[str]:
    """Zmiana mutacji: ``code`` dopisany na końcu modułu."""

    source = (ROOT / module).read_text(encoding="utf-8")
    return [module, source, f"{source}{code}\n"]


def _mutacje(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_mutacja_kodu_kopii_jest_wykryta_mimo_edytowalnej_instalacji_checkoutu() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, "raise SystemExit(3)"), "--", *IMPORT)

    assert answered.returncode == 0, answered.stdout
    assert answered.stdout.splitlines()[-2:] == ["WYKRYTA: mutacja → kod wyjścia 3", "MUTACJE OK"]


def test_mutacja_bez_wplywu_na_polecenie_jest_niewykryta() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, "# bez skutku"), "--", *IMPORT)

    assert answered.returncode == 1
    assert answered.stdout.splitlines()[0].startswith("NIEWYKRYTA: mutacja")


def test_mutacja_w_kilku_plikach_zmienia_wszystkie_naraz(tmp_path: Path) -> None:
    both = "import rozliczenia as r, rozliczenia.message as m; raise SystemExit(getattr(r, 'A', 0) + getattr(m, 'B', 0))"
    mutations = tmp_path / "mutacje.json"
    mutations.write_text(
        json.dumps(
            [
                {
                    "nazwa": "dwa pliki",
                    "zmiany": [_appended(PACKAGE, "A = 1"), _appended("src/rozliczenia/message.py", "B = 1")],
                }
            ]
        ),
        encoding="utf-8",
    )

    answered = _mutacje("--plik", str(mutations), "--", "-c", both)

    assert "WYKRYTA: dwa pliki → kod wyjścia 2" in answered.stdout.splitlines()


def test_mutacja_z_pusta_kotwica_tworzy_plik_w_nowym_katalogu() -> None:
    absent = "import pathlib, sys; sys.exit(pathlib.Path('.nowy/katalog/SKILL.md').is_file())"

    answered = _mutacje("--zmiana", ".nowy/katalog/SKILL.md", "", "skill", "--", "-c", absent)

    assert answered.stdout.splitlines()[-2:] == ["WYKRYTA: mutacja → kod wyjścia 1", "MUTACJE OK"]


@pytest.mark.parametrize("anchor", ["tego tekstu nie ma w pliku", "\n"], ids=["brak", "wiele-razy"])
def test_mutacja_z_kotwica_nie_dokladnie_raz_w_pliku_jest_nieaktualna(anchor: str) -> None:
    answered = _mutacje("--zmiana", PACKAGE, anchor, "", "--", *IMPORT)

    assert answered.returncode == 1
    assert answered.stdout.splitlines()[0].startswith("NIEAKTUALNA: mutacja → kotwicy nie ma dokładnie raz")


def test_polecenie_czerwone_bez_mutacji_nie_daje_werdyktu() -> None:
    answered = _mutacje("--zmiana", *_appended(PACKAGE, ""), "--", "-c", "raise SystemExit(1)")

    assert answered.returncode == 2
    assert answered.stdout.splitlines()[0].startswith("PODSTAWA CZERWONA:")
    assert "WYKRYTA" not in answered.stdout


@pytest.mark.parametrize(
    ("checker", "verdict", "code"),
    [
        ("import rozliczenia\nprint(getattr(rozliczenia, 'RAPORT', 'SPRAWDZENIE OK'))", "WYKRYTA: wynik → SPRAWDZENIE: NARUSZENIE", 0),
        ("print('SPRAWDZENIE: NARUSZENIE')", "PODSTAWA CZERWONA:", 2),
    ],
    ids=["sprawdzenie-dziala", "sprawdzenie-zawsze-zglasza-naruszenie"],
)
def test_mutacja_z_oczekiwana_linia_jest_wykryta_tylko_gdy_bez_mutacji_jej_nie_ma(
    tmp_path: Path, checker: str, verdict: str, code: int
) -> None:
    plan = tmp_path / "mutacje.json"
    change = _appended(PACKAGE, "RAPORT = 'SPRAWDZENIE: NARUSZENIE'")
    plan.write_text(json.dumps([{"nazwa": "wynik", "zmiany": [change], "oczekiwane": "SPRAWDZENIE: NARUSZENIE"}]), encoding="utf-8")

    answered = _mutacje("--plik", str(plan), "--", "-c", checker)

    assert answered.returncode == code, answered.stdout
    assert answered.stdout.splitlines()[0].startswith(verdict), answered.stdout


def test_pusta_lista_mutacji_niczego_nie_dowodzi() -> None:
    answered = subprocess.run(
        [sys.executable, "-c", "import sys\nsys.path.insert(0, 'tools')\nfrom mutacje import check_all\nraise SystemExit(check_all(()))"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert (answered.returncode, answered.stdout.strip()) == (1, "MUTACJE: brak mutacji, więc nie ma czego dowieść")


def test_czesci_tabeli_sprawdzaja_kazda_mutacje_raz_kazda_z_podstawa_tylko_polecen_swoich_mutacji(tmp_path: Path) -> None:
    repo = _small_repository(tmp_path)
    log = tmp_path / "polecenia"

    def command(name: str) -> list[str]:
        seen = "os.environ.get('MUTACJE_CZESC', '-')"
        writes = f"open(os.environ['DZIENNIK'], 'a').write('{name} ' + str(rozliczenia.WARTOSC) + ' ' + {seen} + chr(10))"
        return ["-c", f"import os, rozliczenia\n{writes}\nraise SystemExit(rozliczenia.WARTOSC)"]

    table = [{"nazwa": f"m{number}", "zmiany": [[PACKAGE, "WARTOSC = 0", "WARTOSC = 1"]], "polecenie": command("AB"[number % 2])} for number in range(1, 6)]
    seen = {}
    # Każda część to osobne zadanie CI z tą samą tabelą, a kolejność tabeli nie zmienia podziału.
    for part, order in (("1/3", table), ("2/3", table[::-1]), ("3/3", table[2:] + table[:2]), ("6/6", table)):
        (tmp_path / "mutacje.json").write_text(json.dumps(order), encoding="utf-8")
        log.write_text("", encoding="utf-8")
        answered = _in_repository(repo, "--plik", str(tmp_path / "mutacje.json"), "--", "-c", "", env=WITHOUT_XDIST_WORKERS | {"MUTACJE_CZESC": part, "DZIENNIK": str(log)})
        checked = sorted(line.split()[1] for line in answered.stdout.splitlines() if line.startswith("WYKRYTA: "))
        ran = [line.split() for line in log.read_text(encoding="utf-8").splitlines()]
        baseline = sorted(command for command, value, _ in ran if value == "0")
        # Część dzieli tabelę skryptu, a sprawdzane polecenie zmiennej nie dostaje.
        seen[part] = (answered.returncode, answered.stdout.splitlines()[-1], checked, baseline, {inherited for _, _, inherited in ran})
    broken = _in_repository(repo, "--plik", str(tmp_path / "mutacje.json"), "--", "-c", "", env=WITHOUT_XDIST_WORKERS | {"MUTACJE_CZESC": "0/3", "DZIENNIK": str(log)})

    assert seen == {
        "1/3": (0, "MUTACJE OK", ["m1", "m4"], ["A", "B"], {"-"}),
        "2/3": (0, "MUTACJE OK", ["m2", "m5"], ["A", "B"], {"-"}),
        "3/3": (0, "MUTACJE OK", ["m3"], ["B"], {"-"}),
        "6/6": (0, "MUTACJE OK", [], [], set()),
    }
    assert broken.returncode == 1 and "MUTACJE_CZESC to K/N z 1 <= K <= N, nie '0/3'" in broken.stderr, broken.stderr


def test_kopia_ma_niezacommitowane_zmiany_checkoutu_a_checkout_zostaje_nietkniety(tmp_path: Path) -> None:
    package = "src/rozliczenia"
    repo = repository(
        tmp_path / "repo",
        {
            ".gitignore": "__pycache__/\n",
            **{f"{package}/{name}.py": "WARTOSC = 0\n" for name in ("__init__", "w_indeksie", "poza_indeksem", "usuniety")},
        },
    )
    commit(repo, "baza")
    (repo / package / "w_indeksie.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    git(repo, "add", f"{package}/w_indeksie.py")
    (repo / package / "poza_indeksem.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    (repo / package / "nowy.py").write_text("WARTOSC = 1\n", encoding="utf-8")
    (repo / package / "usuniety.py").unlink()
    status = git(repo, "status", "--porcelain")
    sees_changes = (
        "import importlib.util as u, rozliczenia.w_indeksie as a, rozliczenia.poza_indeksem as b, rozliczenia.nowy as c; "
        "raise SystemExit(0 if a.WARTOSC + b.WARTOSC + c.WARTOSC == 3 and not u.find_spec('rozliczenia.usuniety') else 9)"
    )
    tool = [sys.executable, str(repo / "tools" / "mutacje.py")]

    answered = subprocess.run(
        [*tool, "--zmiana", f"{package}/nowy.py", "WARTOSC = 1", "WARTOSC = 2", "--", "-c", sees_changes],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert answered.stdout.splitlines() == ["WYKRYTA: mutacja → kod wyjścia 9", "MUTACJE OK"]
    assert (git(repo, "status", "--porcelain"), git(repo, "worktree", "list", "--porcelain").count("worktree ")) == (status, 1)


def test_plik_mutacji_spoza_repozytorium_jest_odrzucony_przed_zmiana() -> None:
    answered = _mutacje("--zmiana", str(ROOT / PACKAGE), "x", "y", "--", *IMPORT)

    assert answered.returncode == 2
    assert "plik mutacji musi leżeć w repozytorium" in answered.stderr


@pytest.mark.parametrize(
    ("before", "after"),
    [({"zmiana": "plik"}, {"zmiana/a.txt": "nowy", "zmiana/b.txt": "nowy", "zmiana/c.txt": "nowy"}), ({"zmiana/a.txt": "stary"}, {"zmiana": "nowy"})],
    ids=["plik-w-katalog", "katalog-w-plik"],
)
def test_kopia_ma_sciezke_ktora_zmienila_typ(tmp_path: Path, before: dict[str, str], after: dict[str, str]) -> None:
    repo = repository(tmp_path / "repo", {"src/rozliczenia/__init__.py": "WARTOSC = 0\n", **before})
    commit(repo, "baza")
    if (repo / "zmiana").is_dir():
        shutil.rmtree(repo / "zmiana")
    else:
        (repo / "zmiana").unlink()
    for name, text in after.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    sees_after = (
        "import pathlib, rozliczenia; path = pathlib.Path('zmiana'); "
        "seen = {file.as_posix(): file.read_text() for file in [path, *path.rglob('*')] if file.is_file()}; "
        f"raise SystemExit(0 if seen == {after!r} and rozliczenia.WARTOSC == 0 else 9)"
    )

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje.py"), "--zmiana", "src/rozliczenia/__init__.py", "WARTOSC = 0", "WARTOSC = 1", "--", "-c", sees_after],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert answered.stdout.splitlines() == ["WYKRYTA: mutacja → kod wyjścia 9", "MUTACJE OK"], answered.stderr


def _hanging_repository(path: Path) -> tuple[Path, list[str], Path, Path]:
    """Repozytorium, którego mutacja uruchamia wnuka i wisi; wnuk, póki żyje, dopisuje do pliku co 0,1 s."""

    repo = repository(path / "repo", {"src/rozliczenia/__init__.py": "WISI = False\n"})
    commit(repo, "baza")
    started, beats = path / "wystartowal", path / "wnuk-zyje"
    grandchild = f"import time\nwhile True:\n    open({str(beats)!r}, 'a').write('.')\n    time.sleep(0.1)\n"
    hangs = (
        "import pathlib, subprocess, sys, time, rozliczenia\n"
        "if rozliczenia.WISI:\n"
        f"    subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        f"    while not pathlib.Path({str(beats)!r}).exists():\n"
        "        time.sleep(0.1)\n"
        f"    pathlib.Path({str(started)!r}).touch()\n"
        "    time.sleep(60)\n"
    )
    mutation = ["--zmiana", "src/rozliczenia/__init__.py", "WISI = False", "WISI = True", "--", "-c", hangs]
    return repo, mutation, started, beats


def test_polecenie_bez_wyniku_w_limicie_czasu_daje_przekroczony_czas(tmp_path: Path) -> None:
    repo, mutation, _, _ = _hanging_repository(tmp_path)

    answered = subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje.py"), "--limit-s", "5", *mutation],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )

    assert (answered.returncode, answered.stdout.splitlines()[0]) == (1, "PRZEKROCZONY CZAS: mutacja → brak wyniku po 5 s")


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT do jednego procesu jest sygnałem POSIX")
def test_przerwane_narzedzie_konczy_trwajace_mutacje_i_sprzata(tmp_path: Path) -> None:
    repo, mutation, started, beats = _hanging_repository(tmp_path)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    tool = subprocess.Popen(
        [sys.executable, str(repo / "tools" / "mutacje.py"), *mutation],
        env={**os.environ, "TMPDIR": str(scratch)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.1)

    tool.send_signal(signal.SIGINT)
    tool.wait(timeout=20)
    deadline = time.monotonic() + 20
    while any(scratch.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.1)

    assert (started.exists(), beating(beats)) == (True, False)
    assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert list(scratch.iterdir()) == []


# Środowisko wywołującego bez wartości ``-n auto``, którą ustawia ``tools/szybko.py``.
WITHOUT_XDIST_WORKERS = {name: value for name, value in os.environ.items() if name != "PYTEST_XDIST_AUTO_NUM_WORKERS"}


def _small_repository(path: Path) -> Path:
    repo = repository(path / "repo", {"src/rozliczenia/__init__.py": "WARTOSC = 0\n"})
    commit(repo, "baza")
    return repo


def _plan(path: Path, count: int) -> Path:
    plan = path / "mutacje.json"
    entries = [{"nazwa": f"m{number}", "zmiany": [[PACKAGE, "WARTOSC = 0", "WARTOSC = 1"]]} for number in range(1, count + 1)]
    plan.write_text(json.dumps(entries), encoding="utf-8")
    return plan


def _in_repository(repo: Path, *arguments: str, env: dict[str, str] = WITHOUT_XDIST_WORKERS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "mutacje.py"), *arguments],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    ("arguments", "caller", "seen"),
    [(("--rownolegle",), {}, "1"), (("--rownolegle",), {"PYTEST_XDIST_AUTO_NUM_WORKERS": "3"}, "3"), ((), {}, "brak")],
    ids=["naraz", "naraz-z-wartoscia-wywolujacego", "po-kolei"],
)
def test_mutacje_naraz_daja_zagniezdzonemu_pytest_n_auto_jednego_workera(
    tmp_path: Path, arguments: tuple[str, ...], caller: dict[str, str], seen: str
) -> None:
    """26.10 test każdej z 20 mutacji naraz uruchomił ``pytest -n auto`` z 16 workerami: load 229 na 16 rdzeniach."""

    workers = (
        "import os, rozliczenia; print('workery', os.environ.get('PYTEST_XDIST_AUTO_NUM_WORKERS', 'brak')); "
        "raise SystemExit(rozliczenia.WARTOSC)"
    )

    answered = _in_repository(
        _small_repository(tmp_path), *arguments, "--zmiana", PACKAGE, "WARTOSC = 0", "WARTOSC = 1", "--", "-c", workers, env=WITHOUT_XDIST_WORKERS | caller
    )

    assert answered.stdout.splitlines() == [f"WYKRYTA: mutacja → workery {seen}", "MUTACJE OK"], answered.stderr


def test_naraz_biegnie_najwyzej_osiem_mutacji(tmp_path: Path) -> None:
    """Każda mutacja czeka, aż wystartuje osiem, i podaje, ile biegnie naraz; dziewiąta startuje dopiero po końcu innej."""

    started, running = tmp_path / "wystartowaly", tmp_path / "biegna"
    started.mkdir()
    running.mkdir()
    counts = (
        "import pathlib, time, uuid, rozliczenia\n"
        "if rozliczenia.WARTOSC:\n"
        f"    started, running, me = pathlib.Path({str(started)!r}), pathlib.Path({str(running)!r}), uuid.uuid4().hex\n"
        "    (started / me).touch()\n"
        "    (running / me).touch()\n"
        "    deadline = time.monotonic() + 20\n"
        "    while len(list(started.iterdir())) < 8 and time.monotonic() < deadline:\n"
        "        time.sleep(0.05)\n"
        "    time.sleep(0.5)\n"
        "    print('naraz', len(list(running.iterdir())))\n"
        "    (running / me).unlink()\n"
        "    raise SystemExit(1)\n"
    )

    answered = _in_repository(_small_repository(tmp_path), "--rownolegle", "--plik", str(_plan(tmp_path, 9)), "--", "-c", counts)

    seen = [int(line.rsplit(" ", 1)[1]) for line in answered.stdout.splitlines() if line.startswith("WYKRYTA: m")]
    assert (len(seen), max(seen, default=0)) == (9, 8), answered.stdout + answered.stderr

