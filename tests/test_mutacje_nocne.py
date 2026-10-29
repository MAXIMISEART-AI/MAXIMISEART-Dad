"""Mutacje nocne (ADR 0021): noc mutuje zmiany ``main`` od ostatniej udanej nocy, a przeżyte mutacje trafiają do
jednego issue na PR, który ostatni zmienił ich linię, bez powtórzeń przy kolejnym przebiegu.

Historia ``main`` to prawdziwy Git z PR-ami scalonymi merge'em i squashem, a GitHub to atrapa w pamięci, która
zapamiętuje założone issue i komentarze, więc drugi przebieg widzi skutki pierwszego.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shlex
import sys
from typing import Any, cast
import urllib.parse

import pytest
import yaml

from tests.fixtures.ci_workflow import jobs
from tests.fixtures.git_repo import commit, git, repository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import mutacje_nocne  # noqa: E402
import mutacje_zmiany  # noqa: E402

REPO = "repos/{owner}/{repo}"
RUNY = f"{REPO}/actions/workflows/mutacje-nocne.yml/runs?branch=main&status=success&per_page=1"
TERAZ = datetime(2026, 10, 29, 1, 30, tzinfo=UTC)
RUN = "https://github.com/maximiseartai/MAXIMISEART-Dad/actions/runs/7"
NOCNE = ROOT / ".github" / "workflows" / "mutacje-nocne.yml"


class GitHubWPamieci:
    """Issue z etykietą ``przezyte-mutacje``, ich komentarze i PR-y commitów; zapis zmienia stan, który czyta odczyt."""

    def __init__(self, issues: list[dict[str, Any]] | None = None, pr_commitow: dict[str, list[dict[str, Any]]] | None = None, runy: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []
        self.pr_commitow = pr_commitow or {}
        self.runy = runy or []
        self.wyslane: list[tuple[str, str, Mapping[str, object]]] = []

    def json(self, sciezka: str) -> Any:
        if sciezka == RUNY:
            return {"workflow_runs": self.runy}
        adres, _, zapytanie = sciezka.partition("?")
        parametry = dict(urllib.parse.parse_qsl(zapytanie))
        if commit := re.fullmatch(rf"{re.escape(REPO)}/commits/(\w+)/pulls", adres):
            return self.pr_commitow.get(commit[1], [])
        if adres == f"{REPO}/issues" and parametry.pop("labels") == "przezyte-mutacje" and parametry.pop("state") == "all":
            return self._strona([{key: value for key, value in issue.items() if key != "comments"} for issue in self.issues], parametry)
        if numer := re.fullmatch(rf"{re.escape(REPO)}/issues/(\d+)/comments", adres):
            return self._strona(self._issue(int(numer[1]))["comments"], parametry)
        raise KeyError(sciezka)

    def bajty(self, sciezka: str) -> bytes:
        raise KeyError(sciezka)

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self.wyslane.append((metoda, sciezka, tresc))
        if (metoda, sciezka) == ("POST", f"{REPO}/issues"):
            numer = 900 + len(self.issues)
            self.issues.append({"number": numer, "state": "open", "comments": [], **tresc})
            return {"number": numer}
        issue = self._issue(int(sciezka.split("/")[4]))
        if sciezka.endswith("/comments"):
            issue["comments"].append(dict(tresc))
        elif sciezka.endswith("/labels"):
            issue["labels"] = [*issue.get("labels", []), *cast(list[str], tresc["labels"])]
        else:
            issue.update(tresc)
        return {}

    def _issue(self, numer: int) -> dict[str, Any]:
        return next(issue for issue in self.issues if issue["number"] == numer)

    @staticmethod
    def _strona(wszystkie: list[dict[str, Any]], parametry: dict[str, str]) -> list[dict[str, Any]]:
        rozmiar, strona = int(parametry["per_page"]), int(parametry["page"])
        return wszystkie[(strona - 1) * rozmiar : strona * rozmiar]


def _scal(repo: Path, galaz: str, temat: str) -> str:
    git(repo, "checkout", "--quiet", "main")
    git(repo, "merge", "--quiet", "--no-ff", "--message", temat, galaz)
    return git(repo, "rev-parse", "HEAD")


def _zmien(repo: Path, linia: int, tekst: str) -> None:
    sciezka = repo / "src" / "a.py"
    linie = sciezka.read_text(encoding="utf-8").splitlines()
    linie[linia - 1] = tekst
    sciezka.write_text("\n".join(linie) + "\n", encoding="utf-8")


def _historia(tmp_path: Path) -> tuple[Path, str]:
    """``main``, na którym linie 1 i 5 zmieniły dwa commity scalonego merge'em PR #11, linię 2 squash PR #12, a linie
    3 i 4 commity bez numeru PR w temacie; zwraca repozytorium i bazę nocy sprzed tych zmian."""

    repo = repository(tmp_path / "repo", {"src/a.py": "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"})
    git(repo, "checkout", "--quiet", "-b", "main")
    baza = commit(repo, "baza nocy")
    git(repo, "checkout", "--quiet", "-b", "feat/a")
    _zmien(repo, 1, "a = 10")
    commit(repo, "zmień a")
    _zmien(repo, 5, "e = 50")
    commit(repo, "zmień e")
    _scal(repo, "feat/a", "Merge pull request #11 from org/feat/a")
    _zmien(repo, 2, "b = 20")
    commit(repo, "Zmień b (#12)")
    _zmien(repo, 3, "c = 30")
    commit(repo, "zmień c")
    _zmien(repo, 4, "d = 40")
    commit(repo, "zmień d")
    return repo, baza


def _zapisy(katalog: Path, czesci: dict[int, tuple[str, list[str]]]) -> Path:
    for numer, (wynik, przezyte) in czesci.items():
        (katalog / f"mutacje-nocne-{numer}").mkdir(parents=True)
        (katalog / f"mutacje-nocne-{numer}" / "czesc.json").write_text(json.dumps({"czesc": f"{numer}/3", "wynik": wynik, "przezyte": przezyte}), encoding="utf-8")
    return katalog


PRZEZYLO = "MUTACJE ZMIANY FAIL | przeżyło 2 | mutacje=4 | wyjątki=0 | innego systemu=0"
OK = "MUTACJE ZMIANY OK | mutacje=3 | wyjątki=0 | innego systemu=0"


def test_przezyta_mutacja_trafia_do_issue_pr_ktory_ostatni_zmienil_jej_linie_a_drugi_przebieg_niczego_nie_dubluje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, baza = _historia(tmp_path)
    c, d = git(repo, "rev-parse", "HEAD^"), git(repo, "rev-parse", "HEAD")
    github = GitHubWPamieci(
        issues=[
            {"number": 5, "title": "Przeżyte mutacje z #12", "state": "open", "body": "```\nMUTACJA src/a.py:2 stała\n```", "comments": []},
            {
                "number": 6,
                "title": "Przeżyte mutacje z #14",
                "state": "closed",
                "body": "",
                "comments": [{"body": "MUTACJA src/a.py:3 stała | nie warto, bo tylko log"}],
                "labels": [],
            },
        ],
        pr_commitow={c: [{"number": 14, "merged_at": "2026-10-28T10:00:00Z"}], d: [{"number": 15, "merged_at": None}]},
    )
    # Strona po jednym issue i komentarzu: istniejące issue leżą na różnych stronach, jak przy ponad 100 issue.
    monkeypatch.setattr(mutacje_nocne, "STRONA", 1)
    przezyte = ["src/a.py:1 zmiana linii 1 cofnięta do bazy", "src/a.py:1 `10` zamienione na `0`", "src/a.py:2 stała", "src/a.py:2 `20` → `0`", "src/a.py:5 stała"]
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, przezyte), 2: (OK, []), 3: (PRZEZYLO, ["src/a.py:3 stała", "src/a.py:3 inna", "src/a.py:4 stała"])})

    pierwszy = mutacje_nocne.zglos(github, repo, baza, zapisy, 3, RUN)
    pierwsze_wyjscie = capsys.readouterr().out
    wyslane = list(github.wyslane)
    drugi = mutacje_nocne.zglos(github, repo, baza, zapisy, 3, RUN)

    nowe = {issue["title"]: issue for issue in github.issues if issue["number"] >= 900}
    assert (pierwszy, drugi) == (0, 0), pierwsze_wyjscie
    assert sorted(nowe) == ["Przeżyte mutacje z #11", f"Przeżyte mutacje z commitu {d[:9]}"]
    assert all(issue["labels"] == ["ready-for-agent", "przezyte-mutacje"] for issue in nowe.values())
    tresc_11 = nowe["Przeżyte mutacje z #11"]["body"]
    # Dwa commity PR #11 dają jedno issue.
    assert "MUTACJA src/a.py:1 zmiana linii 1 cofnięta do bazy\nMUTACJA src/a.py:1 `10` zamienione na `0`\nMUTACJA src/a.py:5 stała\n" in tresc_11
    assert RUN in tresc_11 and "nie warto, bo" in tresc_11
    assert "MUTACJA src/a.py:4 stała" in nowe[f"Przeżyte mutacje z commitu {d[:9]}"]["body"]
    # Issue #12 ma już linię „stała”, a #14 zamknięte z powodem dla niej: dostają tylko nowe linie.
    komentarze = {issue["number"]: [komentarz["body"] for komentarz in issue["comments"]] for issue in github.issues if issue["number"] in (5, 6)}
    assert [linia for tekst in komentarze[5] for linia in tekst.splitlines() if linia.startswith("MUTACJA")] == ["MUTACJA src/a.py:2 `20` → `0`"]
    assert [linia for tekst in komentarze[6] for linia in tekst.splitlines() if linia.startswith("MUTACJA")] == [
        "MUTACJA src/a.py:3 stała | nie warto, bo tylko log",
        "MUTACJA src/a.py:3 inna",
    ]
    assert (github.issues[1]["state"], github.issues[1]["labels"]) == ("open", ["ready-for-agent"])
    assert github.wyslane == wyslane
    assert pierwsze_wyjscie.splitlines()[-1] == "MUTACJE NOCNE OK | części 3 | przeżyło 8"


def test_czesc_bez_zapisu_albo_z_porazka_bez_przezytych_czerwieni_przebieg_po_zgloszeniu_reszty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, baza = _historia(tmp_path)
    github = GitHubWPamieci()
    testy_padaja = "MUTACJE ZMIANY FAIL | testy dotknięte zmianą padają bez mutacji, więc mutacje niczego nie dowiodą"
    zapisy = _zapisy(tmp_path / "zapisy", {1: (PRZEZYLO, ["src/a.py:1 stała"]), 3: (testy_padaja, [])})

    kod = mutacje_nocne.zglos(github, repo, baza, zapisy, 3, RUN)

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 1
    assert [issue["title"] for issue in github.issues] == ["Przeżyte mutacje z #11"]
    assert wyjscie[-1].startswith("MUTACJE NOCNE FAIL | część 2/3 bez zapisu: ")
    assert wyjscie[-1].endswith(f"; część 3/3: {testy_padaja}")


def _repo_z_datami(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, str]]:
    repo = repository(tmp_path / "repo", {"src/a.py": "a = 1\n"})
    git(repo, "checkout", "--quiet", "-b", "main")
    shas = {}
    for nazwa, data in (("przedwczoraj", "2026-10-27T10:00:00Z"), ("wczoraj", "2026-10-28T20:00:00Z")):
        monkeypatch.setenv("GIT_COMMITTER_DATE", data)
        (repo / "src" / "a.py").write_text(f"a = {nazwa!r}\n", encoding="utf-8")
        shas[nazwa] = commit(repo, nazwa)
    git(repo, "checkout", "--quiet", "--orphan", "obca")
    shas["obcy"] = commit(repo, "commit spoza main")
    git(repo, "checkout", "--quiet", "main")
    return repo, shas


@pytest.mark.parametrize(
    ("od", "run", "oczekiwana", "skad"),
    [
        ("", "wczoraj", "wczoraj", "ostatni udany run 41"),
        ("", None, "przedwczoraj", "24 h wstecz, bez udanego runu przodka HEAD"),
        ("", "obcy", "przedwczoraj", "24 h wstecz, bez udanego runu przodka HEAD"),
        ("przedwczoraj", "wczoraj", "przedwczoraj", "--od przedwczoraj"),
    ],
    ids=["ostatni-udany-run", "bez-udanego-runu", "run-spoza-historii-head", "od-z-recznego-uruchomienia"],
)
def test_noc_mutuje_od_ostatniego_udanego_przebiegu_a_bez_niego_od_24_h_wstecz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, od: str, run: str | None, oczekiwana: str, skad: str
) -> None:
    repo, shas = _repo_z_datami(tmp_path, monkeypatch)
    github = GitHubWPamieci(runy=[{"id": 41, "head_sha": shas[run]}] if run else [])

    znaleziona = mutacje_nocne.baza(github, repo, shas[od] if od else "", TERAZ)

    assert znaleziona == (shas[oczekiwana], skad.replace("--od przedwczoraj", f"--od {shas['przedwczoraj']}"))


ZLY_WYJATEK = "src/pakiet/a.py:4: wyjątek musi mieć postać `# mutacje-zmiany: <powód> | do RRRR-MM-DD | zgoda <kto>`"


@pytest.mark.parametrize(
    ("dopisane", "mutacje", "czesci"),
    [
        # Z mutacji nowej linii ``return`` biegnie jedna, granica porównania, i cofnięcie fragmentu.
        ("\n\ndef b(x: int) -> bool:\n    return x < 3\n", 2, [1, 2]),
        ("", 0, []),
        # Sam komentarz nie ma mutacji, ale część zgłasza zły wyjątek jako MUTACJE ZMIANY FAIL.
        ("\n# mutacje-zmiany: bez terminu\n", 1, [1]),
    ],
    ids=["zmiana-src", "bez-zmiany", "zly-wyjatek"],
)
def test_plan_dzieli_mutacje_od_bazy_na_czesci_dla_macierzy_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], dopisane: str, mutacje: int, czesci: list[int]
) -> None:
    repo = repository(tmp_path / "repo", {"src/pakiet/a.py": "def a(x: int) -> bool:\n    return x > 1\n"})
    baza = commit(repo, "baza")
    if dopisane:
        with (repo / "src" / "pakiet" / "a.py").open("a", encoding="utf-8") as plik:
            plik.write(dopisane)
        commit(repo, "zmiana")
    for modul in (mutacje_nocne, mutacje_zmiany):
        monkeypatch.setattr(modul, "ROOT", repo)
    monkeypatch.setattr(mutacje_nocne, "NA_CZESC", 1)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))

    kod = mutacje_nocne.main(["plan", "--od", baza])

    wyjscie = capsys.readouterr().out.splitlines()
    assert kod == 0, wyjscie
    assert wyjscie[-1] == f"MUTACJE NOCNE PLAN | baza {baza} (--od {baza}) | mutacje {mutacje} | części {len(czesci)}"
    assert (f"MUTACJE NOCNE | {ZLY_WYJATEK}; część mutacji to zgłosi" in wyjscie) == (mutacje == 1)
    output = dict(linia.split("=", 1) for linia in (tmp_path / "output").read_text(encoding="utf-8").splitlines())
    assert output == {"baza": baza, "czesci": json.dumps(czesci), "liczba": str(len(czesci))}


@pytest.mark.parametrize(("mutacje", "czesci"), [(0, 0), (1, 1), (25, 1), (26, 2), (500, 20), (10_000, 20)])
def test_czesc_ma_najwyzej_25_mutacji_ale_noc_najwyzej_20_czesci(mutacje: int, czesci: int) -> None:
    assert mutacje_nocne.czesci(mutacje) == czesci


def _nocne() -> dict[Any, Any]:
    wczytany: dict[Any, Any] = yaml.safe_load(NOCNE.read_text(encoding="utf-8"))
    return wczytany


def test_noc_biegnie_raz_na_dobe_i_recznie_z_opcjonalnym_od_a_dwa_przebiegi_nie_biegna_naraz() -> None:
    workflow = _nocne()
    # PyYAML czyta klucz ``on`` jako True.
    wyzwalacze = workflow[True]

    assert [re.fullmatch(r"\d+ \d+ \* \* \*", wpis["cron"]) is not None for wpis in wyzwalacze["schedule"]] == [True]
    assert wyzwalacze["workflow_dispatch"]["inputs"]["od"]["required"] is False
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_kazda_czesc_mutuje_od_bazy_planu_i_wgrywa_zapis_pod_nazwa_ktora_czyta_zgloszenie() -> None:
    zadania = _nocne()["jobs"]
    czesc = zadania["change-mutations"]
    krok = next(krok for krok in czesc["steps"] if "tools/mutacje_zmiany.py" in krok.get("run", ""))
    polecenie = shlex.split(krok["run"])
    zapis = polecenie[polecenie.index("--zapis") + 1]
    wgranie = next(krok for krok in czesc["steps"] if "upload-artifact" in krok.get("uses", ""))
    zgloszenie = zadania["zgloszenie"]
    pobranie = next(krok for krok in zgloszenie["steps"] if "download-artifact" in krok.get("uses", ""))
    polecenie_zgloszenia = shlex.split(next(krok["run"] for krok in zgloszenie["steps"] if "zglos" in krok.get("run", "")))

    assert (czesc["needs"], czesc["strategy"]["matrix"]["czesc"]) == ("plan", "${{ fromJSON(needs.plan.outputs.czesci) }}")
    assert krok["env"] == {"BAZA": "${{ needs.plan.outputs.baza }}", "CZESC": "${{ matrix.czesc }}/${{ needs.plan.outputs.liczba }}"}
    assert polecenie[polecenie.index("--baza") + 1] == "$BAZA" and polecenie[polecenie.index("--czesc") + 1] == "$CZESC"
    # Przeżyte mutacje kończą narzędzie kodem 1, a o części rozstrzyga zgłoszenie z jej zapisu.
    assert krok["continue-on-error"] is True
    assert (Path(zapis).name, wgranie["with"]["path"], wgranie["with"]["name"]) == (mutacje_nocne.ZAPIS, zapis, f"{mutacje_nocne.ARTEFAKT}${{{{ matrix.czesc }}}}")
    assert (pobranie["with"]["pattern"], polecenie_zgloszenia[polecenie_zgloszenia.index("--zapisy") + 1]) == (f"{mutacje_nocne.ARTEFAKT}*", pobranie["with"]["path"])
    # Zgłoszenie biegnie też po części, która padła, i ma prawo zakładać issue.
    assert zgloszenie["if"].startswith("${{ !cancelled() && needs.plan.result == 'success'")
    assert zgloszenie["permissions"]["issues"] == "write"


def _instalacje_na_linuksie(zadanie: dict[str, Any]) -> list[str]:
    return [krok["run"] for krok in zadanie["steps"] if "uv pip install" in krok.get("run", "") and "'Windows'" not in krok.get("if", "")]


def test_czesc_instaluje_to_samo_co_czesci_pytest_na_linuksie() -> None:
    # Część uruchamia testy dotknięte zmianą, a testy tools/scal_pr.py i tools/scalenia_pr.py wołają ruff i mypy.
    assert _instalacje_na_linuksie(_nocne()["jobs"]["change-mutations"]) == _instalacje_na_linuksie(jobs()["pytest"])
