"""Jedyna droga merge'a PR przez agenta: ``gh pr merge`` tylko po sprawdzeniu gotowości tuż przed nim.

Narzędzie scala PR numer N do jego bazy, gdy jednocześnie:

1. PR jest otwarty, nie jest szkicem i nie pochodzi z forka (z forka ruff i mypy biegłyby na obcym kodzie);
2. check ``Required CI status`` z GitHub Actions na HEAD PR skończył się sukcesem (jak w rulesecie ``main``:
   CheckRun z workflow, nie status commitu, który może ustawić każdy z prawem zapisu);
3. najnowszy werdykt dla HEAD PR to ``PASS``;
4. opis PR ma każdy nagłówek ``##`` wzoru z ``.agents/skills/pr/SKILL.md``, każdy jako osobną linię i w kolejności
   wzoru, więc każdy PR ma te same sekcje, a sekcja dopisana do wzoru od razu obowiązuje;
5. HEAD PR scala się z bieżącą bazą z ``origin`` bez konfliktu, a ruff i mypy dla obu systemów przechodzą na
   scalonym drzewie (``scalenia_pr.merge_verdict``, jak status ``scalenie z main``, ale teraz, nie po pushu).

Mutacje zmienionych linii nie biegną na PR i nie czeka na nie: biegną nocą na ``main`` (ADR 0021,
``tools/mutacje_nocne.py``).

Werdykty to komentarze i recenzje PR kont z prawem zapisu (``OWNER``, ``MEMBER``, ``COLLABORATOR``), w kolejności
utworzenia; nieopublikowana recenzja (``PENDING``) się nie liczy. Werdykt to komentarz albo recenzja, której pierwsza
niepusta linia, bez odstępów na brzegach, to dokładnie ``WERDYKT: PASS <SHA>`` (zgoda) albo ``WERDYKT: FAIL <SHA>``
(sprzeciw), gdzie ``<SHA>`` to pełny SHA HEAD PR małymi literami; dalsze linie to znaleziska i ich nie czyta.
Sprzeciwem jest też recenzja w stanie ``CHANGES_REQUESTED``. Inny tekst, także ``FAIL`` w prozie albo werdykt ze
skróconym SHA, nie jest werdyktem. Zgodę pisze niezależny recenzent, nie autor zmiany: ``PASS`` mówi, że przegląd
nie znalazł problemów, a skille ``verify-*`` z linii ``SKILLE VERIFY`` ``tools/skille_dla_zmiany.py`` przeszły na
tym SHA (ich polecenia z linii ``LICZY CI`` w CI, reszta workflow u agenta). Rozstrzyga najnowszy werdykt dla HEAD:
sprzeciw po ``PASS`` odbiera zgodę, nowszy ``PASS`` ją przywraca, a werdykt starszego commitu nie przechodzi na nowy
push. Komentarz edytowany liczy się z treścią po edycji, ale w miejscu utworzenia, a ukryty komentarz nadal się liczy.

Gdy któryś warunek nie zachodzi, narzędzie nie scala i kończy się linią ``SCAL ODMOWA | #N <sha> | <przyczyny>``.
Warunki 1–4 sprawdza razem i podaje wszystkie przyczyny; warunek 5 trwa dłużej, więc biegnie dopiero po nich.
Przed merge'em sprawdza, że baza w ``origin`` nie przesunęła się w trakcie sprawdzania, a ``gh pr merge
--match-head-commit`` odrzuca PR, którego HEAD zmienił się po sprawdzeniu. Po merge'u uruchamia
``tools/sprzatanie.py``, jeśli istnieje, i podaje ostatnią linię jego raportu: bez ``--usun`` sprzątanie niczego nie
usuwa, tylko mówi, które lokalne gałęzie i worktree można usunąć. Sprzątanie, które przekroczy czas, kończy się
ostrzeżeniem w linii ``SCAL OK``, bo PR jest już scalony.

Po merge'u do domyślnej gałęzi repozytorium, przed sprzątaniem, zamyka jego otwarte issues, które opis PR wskazuje
słowem „Naprawia”. GitHub tego słowa nie zna, więc bez narzędzia takie issues zostawały otwarte. Każde dostaje
komentarz z numerem PR i pełnym SHA commitu merge'a, a linia ``SCAL OK`` podaje ``zamknięte: #N``. Opis bez słowa
„Naprawia” pomija bez pytania GitHuba. Z nim pyta o domyślną gałąź (``gh repo view``), a przy merge'u do niej
renderuje opis rendererem GitHuba (``gh api markdown``, ``mode=gfm``, ``context`` to repozytorium PR), więc to GitHub
decyduje, co jest kodem, cytatem albo komentarzem HTML.

Issue się liczy, gdy GitHub zamienił jego odwołanie na link do issue tego repozytorium (bez względu na wielkość liter
właściciela i nazwy), a link stoi na liście numerów zaraz po słowie „Naprawia”, pisanym dokładnie tak, od wielkiej
litery, które zaczyna linię akapitu albo punktu listy. Linia liczy się tylko wtedy, gdy jej tekst zaczyna się
w akapicie albo punkcie listy, a wszystko, w czym ten blok stoi, to akapity, punkty i listy; w samym bloku tekst może
stać jeszcze w pogrubieniu albo kursywie. Każde inne miejsce niczego nie zamyka, także takie, którego tu nie wymieniono
i którego GitHub dopiero zacznie używać: nagłówek, tabela, ``<details>`` i ``<summary>``, cytat i alert GitHuba
(``> [!NOTE]``), blok HTML (``<div>``, ``<section>``, ``<dl>``), przypis i ``<pre>``, także gdy GitHub owinie tekst
w nich w akapit albo punkt listy. Linię kończy tylko ``<br>``, którym GitHub zastępuje koniec wiersza, oraz początek
i koniec bloku: akapitu, punktu listy, nagłówka, cytatu, tabeli, ``<pre>``, ``<div>``, ``<details>``, ``<summary>``
i ``<hr>``. Każdy inny znacznik (``<q>``, ``<kbd>``, emoji, wzór ``$…$`` i każdy, którego GitHub dopiero zacznie
używać) należy do linii, a jego tekst się liczy, poza kodem i przekreśleniem. Liczy się więc ``Naprawia #490``,
``Naprawia #490, #491 i #492 oraz #493``, kilka linii, także pogrubionych, i adres issue. Lista kończy się na
pierwszym tekście innym niż przecinek, „i”, „oraz” albo numer, którego GitHub nie zlinkował (nieistniejący): „Naprawia
#490. Nie naprawia #491” zamyka tylko #490. Kończy ją też odwołanie do innego repozytorium: w ``Naprawia
MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia#12, #13`` GitHub linkuje ``#13`` do tego repo, ale autor wylicza tam
Zgłoszenia. Zgłoszenie zostaje otwarte, bo zamknięte mówi Centrum taty, że poprawka czeka na aktualizację, a merge do
``main`` to jeszcze nie Wydanie. Nie zamyka: „Naprawia” w środku linii (także „Ten PR <q>nie</q> Naprawia #490”),
„naprawia” małą literą (także w zawiniętej linii „Ten PR nie do końca⏎naprawia #490”), linii, która zaczyna się od
kodu, przekreślenia (także takich, które zaczęły się przed końcem poprzedniego wiersza: ``~~Ten PR⏎nie~~ Naprawia
#490``), obrazka albo pola punktu listy zadań (``- [ ] Naprawia #490``), linii spoza akapitów i list (wyżej), kodu
(fragmentu, bloku i ``<pre>``), przekreślenia, PR-a, issue już zamkniętego ani issues, które GitHub zamyka sam
(``closingIssuesReferences``: ``Closes``, ``Fixes``, ``Resolves``).

Merge do innej gałęzi niż domyślna (stos PR-ów) niczego nie zamyka i nie renderuje opisu, jak GitHub przy ``Closes``,
a linia podaje ``bez zamykania „Naprawia”: baza <gałąź> to nie <domyślna>``. Gdy GitHub nie poda domyślnej gałęzi
albo nie wyrenderuje opisu (``gh`` z błędem albo po czasie, pusta odpowiedź), narzędzie niczego nie zamyka, tylko
ostrzega ``UWAGA: GitHub nie podał domyślnej gałęzi`` albo ``UWAGA: GitHub nie wyrenderował opisu PR`` z dopiskiem
``nie zamknięto issues z „Naprawia”, zamknij je ręcznie``. Gdy GitHub po merge'u nie poda commitu merge'a, narzędzie
nie zamyka, bo nie wie, czy PR wszedł do gałęzi (np. czeka w kolejce merge'a), tylko ostrzega ``UWAGA: GitHub nie
podał commitu merge'a, nie zamknięto #N, zamknij ręcznie``. Każdy błąd przy zamykaniu (``gh`` z błędem albo po
czasie, odpowiedź bez stanu issue) kończy się ostrzeżeniem ``UWAGA: nie zamknięto #N, zamknij ręcznie``. Każde z tych
ostrzeżeń stoi w linii ``SCAL OK`` z kodem 0, bo PR jest już scalony. Z ``--bez-merge`` tylko czyta, niczego nie
zamyka, a linia podaje ``po merge'u zamknie: #N`` (a zamiast „nie zamknięto …” ostrzeżenia ``nie sprawdzono …``).

Kod 0 i ``SCAL OK`` znaczą, że PR jest scalony (albo z ``--bez-merge``: że byłby); linia po merge'u podaje SHA
commitu merge'a i bazy, z którą sprawdziła scalenie. Kod 1 to odmowa albo błąd narzędzia (``SCAL FAIL``).

Komentarze, recenzje i checki pochodzą z jednego ``gh pr view --json``, które doczytuje wszystkie strony
komentarzy (sprawdzone na PR z 337 komentarzami, gh 2.101).

    .venv/bin/python tools/scal_pr.py 336               # sprawdza i scala
    .venv/bin/python tools/scal_pr.py 336 --bez-merge   # tylko sprawdza
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

import potomne
import scalenia_pr

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECK = "Required CI status"
VERDICT_LINE = re.compile(r"WERDYKT: (PASS|FAIL) ([0-9a-f]{40})")
TRUSTED = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
CLEANUP = ROOT / "tools" / "sprzatanie.py"
TEMPLATE = ROOT / ".agents" / "skills" / "pr" / "SKILL.md"
CLEANUP_TIMEOUT_S = 300
LINK = "\x01"
NOT_TEXT = "\x00"
_REFERENCE = rf"(?:{LINK}|(?:[\w.-]+/[\w.-]+)?#\d+)"
FIXES = re.compile(rf"\s*Naprawia\s+({_REFERENCE}(?:\s*(?:,|\bi\b|\boraz\b)\s*{_REFERENCE})*)")
REFERENCE = re.compile(_REFERENCE)
BLOCKS = frozenset({"blockquote", "details", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "p", "pre", "summary", "table"})
LIST_OR_PARAGRAPH = frozenset({"li", "ol", "p", "ul"})
EMPHASIS = frozenset({"em", "strong"})
HIDDEN = frozenset({"code", "del", "s", "strike"})
VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"})


@dataclass(frozen=True)
class Pull:
    number: int
    title: str
    head: str
    base: str
    problems: tuple[str, ...]
    verdicts: tuple[dict[str, object], ...]
    repository: str
    body: str
    closed_by_github: frozenset[int]


class _Refused(Exception):
    pass


def _gh(*arguments: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["gh", *arguments],
        input=stdin,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=scalenia_pr.GITHUB_TIMEOUT_S,
        check=True,
    )
    return done.stdout


def _ci_problem(rollup: list[dict[str, str | None]]) -> str | None:
    results = []
    for check in rollup:
        if check.get("name") == REQUIRED_CHECK and check.get("workflowName"):
            completed = check.get("status") == "COMPLETED"
            results.append((check.get("conclusion") if completed else check.get("status")) or "?")
    if not results:
        return f"CI: brak „{REQUIRED_CHECK}” z GitHub Actions na HEAD"
    failed = [result for result in results if result != "SUCCESS"]
    return f"CI: „{REQUIRED_CHECK}” {', '.join(failed)}" if failed else None


def _body_problem(body: str) -> str | None:
    """Przyczyna odmowy, gdy opisowi brakuje nagłówka wzoru albo ma go nie po poprzednim; wzór to blok ``markdown``."""

    template = TEMPLATE.read_text(encoding="utf-8").partition("```markdown\n")[2].partition("\n```")[0]
    lines = [line.strip() for line in body.splitlines()]
    missing, after = [], 0
    for heading in (line for line in template.splitlines() if line.startswith("## ")):
        if heading in lines[after:]:
            after = lines.index(heading, after) + 1
        else:
            missing.append(heading)
    if not missing:
        return None
    return f"opis: brak {', '.join(f'„{heading}”' for heading in missing)} w kolejności wzoru {TEMPLATE.relative_to(ROOT).as_posix()}"


def _verdict(verdict: dict[str, object], head: str) -> str | None:
    """``PASS`` albo ``FAIL`` dla ``head``; ``None``, gdy komentarz albo recenzja nie jest werdyktem dla ``head``."""

    if verdict["authorAssociation"] not in TRUSTED or verdict.get("state") == "PENDING":
        return None
    if verdict.get("state") == "CHANGES_REQUESTED":
        return "FAIL"
    lines = [line.strip() for line in str(verdict["body"]).splitlines() if line.strip()]
    found = VERDICT_LINE.fullmatch(lines[0]) if lines else None
    return found[1] if found and found[2] == head else None


def _verdict_problem(verdicts: tuple[dict[str, object], ...], head: str) -> str | None:
    """Przyczyna odmowy z najnowszego werdyktu dla ``head`` z werdyktów w kolejności utworzenia."""

    latest = None
    for verdict in verdicts:
        latest = _verdict(verdict, head) or latest
    if latest is None:
        return f"werdykt: brak komentarza ani recenzji „WERDYKT: PASS {head}”"
    return None if latest == "PASS" else f"werdykt: FAIL dla {head[:7]} bez nowszego „WERDYKT: PASS {head}”"


@dataclass(frozen=True)
class _Link:
    repository: str
    number: int
    issue: bool


class _Lines(HTMLParser):
    """Linie akapitów i punktów list w HTML opisu PR: ``LINK`` w miejscu linku do issue albo PR, ``NOT_TEXT`` w miejscu kodu, przekreślenia, obrazka i pola wyboru.

    Linię kończy ``<br>`` i początek albo koniec bloku z ``BLOCKS``, a każdy inny znacznik należy do linii. Linia
    trafia do ``lines`` tylko wtedy, gdy jej tekst zaczyna się wewnątrz samych ``LIST_OR_PARAGRAPH`` i ``EMPHASIS``,
    a najgłębszy z tych bloków to akapit albo punkt listy.
    """

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[list[str | _Link]] = []
        self._line: list[str | _Link] = []
        self._start: tuple[str, ...] | None = None
        self._open: list[str] = []
        self._link: _Link | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in BLOCKS or tag == "br":
            self._end_line()
        if tag in {"img", "input"} or (tag in HIDDEN and not self._hidden()):
            self._append(NOT_TEXT)
        elif tag == "a" and not self._hidden() and "issue-link" in (attributes.get("class") or "").split():
            _, owner, name, _, number = urlsplit(attributes.get("data-url") or "").path.split("/")
            self._link = _Link(f"{owner}/{name}", int(number), attributes.get("data-hovercard-type") == "issue")
        if tag not in VOID:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCKS:
            self._end_line()
        if tag in self._open:
            del self._open[len(self._open) - 1 - self._open[::-1].index(tag) :]
        if tag == "a" and self._link is not None:
            self._line.append(self._link)
            self._link = None

    def handle_data(self, data: str) -> None:
        if not self._hidden() and self._link is None:
            self._append(data)

    def _hidden(self) -> bool:
        return not HIDDEN.isdisjoint(self._open)

    def _append(self, part: str) -> None:
        if self._start is None and part.strip():
            self._start = tuple(self._open)
        self._line.append(part)

    def _end_line(self) -> None:
        blocks = [tag for tag in self._start or () if tag not in EMPHASIS]
        if blocks and blocks[-1] in {"p", "li"} and LIST_OR_PARAGRAPH.issuperset(blocks):
            self.lines.append(self._line)
        self._line, self._start = [], None
        if self._hidden():
            self._append(NOT_TEXT)  # kod albo przekreślenie przechodzi przez ``<br>`` na początek następnej linii


def fixed_issues(body: str, repository: str) -> tuple[int, ...]:
    """Numery issues ``repository`` z linii „Naprawia” opisu PR ``body`` wyrenderowanego przez GitHuba.

    Rzuca wyjątek, gdy GitHub opisu nie wyrenderował.
    """

    rendered = _gh("api", "markdown", "--input", "-", stdin=json.dumps({"text": body, "mode": "gfm", "context": repository}))
    if not rendered.strip():
        raise ValueError("GitHub zwrócił pusty HTML")
    parser = _Lines()
    parser.feed(rendered)
    parser.close()
    numbers: list[int] = []
    for line in parser.lines:
        listed = FIXES.match("".join(LINK if isinstance(part, _Link) else part for part in line))
        links = iter(part for part in line if isinstance(part, _Link))
        for reference in REFERENCE.finditer(listed[1] if listed else ""):
            if reference[0] != LINK:
                if "/" in reference[0]:
                    break
                continue
            link = next(links)
            if link.repository.casefold() != repository.casefold():
                break
            if link.issue and link.number not in numbers:
                numbers.append(link.number)
    return tuple(numbers)


def _pull(number: int) -> Pull:
    fields = (
        "number,title,state,isDraft,isCrossRepository,baseRefName,headRefOid,statusCheckRollup,comments,reviews,"
        "url,body,closingIssuesReferences"
    )
    pull = json.loads(_gh("pr", "view", str(number), "--json", fields))
    problems = []
    if pull["state"] != "OPEN":
        problems.append(f"PR nie jest otwarty: {pull['state']}")
    if pull["isDraft"]:
        problems.append("PR jest szkicem")
    if pull["isCrossRepository"]:
        problems.append("PR z forka")
    problems += filter(None, [_ci_problem(pull["statusCheckRollup"]), _body_problem(pull["body"])])
    verdicts = [*pull["comments"], *pull["reviews"]]
    verdicts.sort(key=lambda verdict: verdict.get("createdAt") or verdict.get("submittedAt") or "")
    repository = "/".join(pull["url"].split("/")[3:5])
    closed_by_github = frozenset(
        issue["number"]
        for issue in pull["closingIssuesReferences"]
        if f"{issue['repository']['owner']['login']}/{issue['repository']['name']}".casefold() == repository.casefold()
    )
    return Pull(
        number,
        pull["title"],
        pull["headRefOid"],
        pull["baseRefName"],
        tuple(problems),
        tuple(verdicts),
        repository,
        pull["body"],
        closed_by_github,
    )


def _remote_base(base: str) -> str:
    listed = potomne.run(["git", "ls-remote", "origin", f"refs/heads/{base}"], cwd=ROOT, timeout=scalenia_pr.GITHUB_TIMEOUT_S)
    listed.check_returncode()
    return listed.stdout.partition("\t")[0]


def _check(pull: Pull) -> str:
    """SHA bazy, z którą scalenie przeszło."""

    checked = scalenia_pr.PullRequest(pull.number, pull.title, pull.head)
    base = scalenia_pr.fetch(pull.base, [checked])
    problems = [*pull.problems, *filter(None, [_verdict_problem(pull.verdicts, pull.head)])]
    if problems:
        raise _Refused("; ".join(problems))
    where = f"{pull.base} {base[:7]}"
    print(f"== #{pull.number} {pull.head[:7]} na {where}", flush=True)
    with potomne.commit_copy(ROOT, base) as copy:
        verdict = scalenia_pr.merge_verdict(copy, where, base, None, checked)
    if verdict.state != "success":
        raise _Refused(verdict.description)
    return base


def _close_fixed(pull: Pull, *, merged: bool, merge_commit: str | None) -> str:
    """Zamyka otwarte issues z linii „Naprawia” z komentarzem o merge'u, a przed merge'em tylko je podaje."""

    if "Naprawia" not in pull.body:
        return ""
    unchecked = "nie zamknięto issues z „Naprawia”, zamknij je ręcznie" if merged else "nie sprawdzono „Naprawia”"
    try:
        default_branch = str(json.loads(_gh("repo", "view", pull.repository, "--json", "defaultBranchRef"))["defaultBranchRef"]["name"])
    except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
        return f" | UWAGA: GitHub nie podał domyślnej gałęzi, {unchecked}"
    if pull.base != default_branch:
        return f" | bez zamykania „Naprawia”: baza {pull.base} to nie {default_branch}"
    try:
        fixes = [number for number in fixed_issues(pull.body, pull.repository) if number not in pull.closed_by_github]
    except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
        return f" | UWAGA: GitHub nie wyrenderował opisu PR, {unchecked}"
    closes = merged and merge_commit is not None
    open_issues, failed = [], []
    for number in fixes:
        try:
            if json.loads(_gh("api", f"repos/{pull.repository}/issues/{number}"))["state"] != "open":
                continue
            if closes:
                comment = f"Naprawione przez #{pull.number}, scalone jako {merge_commit}."
                _gh("issue", "close", str(number), "--repo", pull.repository, "--comment", comment)
            open_issues.append(f"#{number}")
        except Exception:  # noqa: BLE001 - po merge'u każdy błąd to tylko ostrzeżenie w linii SCAL OK, bo PR jest już scalony
            failed.append(f"#{number}")
    if merged and not closes:
        missed = [*open_issues, *failed]
        return f" | UWAGA: GitHub nie podał commitu merge'a, nie zamknięto {', '.join(missed)}, zamknij ręcznie" if missed else ""
    done, warning = ("zamknięte", "UWAGA: nie zamknięto {}, zamknij ręcznie") if merged else (
        "po merge'u zamknie", "UWAGA: nie sprawdzono {}"
    )
    parts = [f"{done}: {', '.join(open_issues)}"] if open_issues else []
    parts += [warning.format(", ".join(failed))] if failed else []
    return "".join(f" | {part}" for part in parts)


def _merge_commit(number: int) -> str | None:
    """SHA commitu merge'a scalonego PR albo ``None``, gdy GitHub go nie podał."""

    try:
        return str(json.loads(_gh("pr", "view", str(number), "--json", "mergeCommit"))["mergeCommit"]["oid"])
    except Exception:  # noqa: BLE001 - PR jest już scalony, a brak SHA podaje linia SCAL OK
        return None


def _clean_up() -> str:
    if not CLEANUP.exists():
        return f"sprzątanie pominięte: brak {CLEANUP.relative_to(ROOT).as_posix()}"
    try:
        done = potomne.run([sys.executable, str(CLEANUP)], cwd=ROOT, timeout=CLEANUP_TIMEOUT_S, echo=True)
    except subprocess.TimeoutExpired:
        return f"UWAGA: sprzątanie przerwane po {CLEANUP_TIMEOUT_S} s, uruchom je ponownie"
    result = done.stdout.rstrip().rpartition("\n")[2]
    return f"sprzątanie: {result or f'kod {done.returncode}'}"


def _merge(number: int, *, merge: bool) -> int:
    pull = _pull(number)
    where = f"#{pull.number} {pull.head[:7]}"
    try:
        base = _check(pull)
        if merge and _remote_base(pull.base) != base:
            raise _Refused(f"{pull.base} zmienił się w trakcie sprawdzania, uruchom ponownie")
    except _Refused as refusal:
        print(f"SCAL ODMOWA | {where} | {refusal}")
        return 1
    if not merge:
        print(f"SCAL OK | {where} | gotowy do merge'a z {pull.base} {base[:7]}, bez merge'a (--bez-merge){_close_fixed(pull, merged=False, merge_commit=None)}")
        return 0
    _gh("pr", "merge", str(number), "--merge", "--match-head-commit", pull.head)
    merge_commit = _merge_commit(number)
    closed = _close_fixed(pull, merged=True, merge_commit=merge_commit)
    print(f"SCAL OK | {where} | scalony do {pull.base} jako {(merge_commit or '?')[:7]} (baza {base[:7]}){closed} | {_clean_up()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("numer", type=int, help="Numer PR.")
    parser.add_argument("--bez-merge", action="store_true", help="Sprawdź gotowość, ale nie scalaj.")
    args = parser.parse_args(argv)
    try:
        return _merge(args.numer, merge=not args.bez_merge)
    except subprocess.CalledProcessError as error:
        command = " ".join(str(part) for part in error.cmd)
        print(f"SCAL FAIL | {command}: {(error.stderr or error.stdout or '').strip()}")
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"SCAL FAIL | {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
