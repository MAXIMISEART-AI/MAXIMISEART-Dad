"""Hooki Claude Code ``tools/hooks/czekanie.py`` i ``tools/hooks/zgoda.py`` jako własności Hypothesis.

Parsery poleceń w hookach padały w przeglądzie na wejściach, których autor nie przewidział: wzorzec ``rg`` ze słowem
pętli dostawał odmowę, ``&>`` było tłem, a wzorzec z zagnieżdżonym kwantyfikatorem liczył się w czasie wykładniczym
(#446); ``$(`` w apostrofach, ``sh -c '…'`` i zamiana cudzysłowów zmieniały werdykt (#496). Autor sprawdzał się na
przykładach z tym samym założeniem co kod, więc fałszywych odmów nie widział.

Tu oczekiwanie bierze się z docstringów hooków i tabeli reguł w ``AGENTS.md``: czekanie na CI albo pętla na
``pgrep -f`` na pierwszym planie dostaje odmowę, a reszta przechodzi. To, czym napis jest dla powłoki, rozstrzyga
wyrocznia niezależna od hooka: ``shlex`` (tekst jest jednym argumentem, cudzysłów nie zmienia słów polecenia) i
``bash -n`` (wygenerowane polecenie jest poprawne składniowo). Przykłady są deterministyczne (``derandomize=True``,
bez bazy przykładów), a czas mierzy stosunek czasów dwóch długości wejścia, więc nie zależy od szybkości runnera.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
import importlib.util
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from types import ModuleType
from unittest import mock

import pytest
from hypothesis import Phase, example, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
CZEKANIE = ROOT / "tools" / "hooks" / "czekanie.py"
ZGODA = ROOT / "tools" / "hooks" / "zgoda.py"

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=150)


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"wlasnosci_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


czekanie = _load(CZEKANIE)
zgoda = _load(ZGODA)
REFUSALS = {"ci": czekanie.CI_LOOP, "pgrep": czekanie.PGREP_LOOP, "watch": czekanie.WATCHING}


@dataclass(frozen=True)
class Case:
    """Polecenie i odmowy, które według docstringu hooka może dostać (pusty zbiór: przechodzi)."""

    text: str
    refusals: frozenset[str]


@dataclass(frozen=True)
class Template:
    """Polecenie z argumentami, które można ująć w cudzysłowy, bo nie są słowem kluczowym ani nazwą polecenia."""

    form: str
    arguments: tuple[str, ...]
    refusals: frozenset[str]

    def text(self, quotes: Sequence[str] = ()) -> str:
        padded = (*quotes, *[""] * len(self.arguments))[: len(self.arguments)]
        return self.form.format(
            *(quote + argument + quote for quote, argument in zip(padded, self.arguments, strict=True))
        )


def _judged(text: str) -> frozenset[str]:
    refusal = czekanie.judge(text, in_background=False)
    return frozenset(name for name, known in REFUSALS.items() if refusal is known) if refusal else frozenset()


def _verdict_matches(case: Case) -> bool:
    judged = _judged(case.text)
    return judged <= case.refusals and bool(judged) == bool(case.refusals)


NUMBERS = st.integers(1, 99999).map(str)
SECONDS = st.integers(1, 120).map(str)
NAMES = st.sampled_from(("bench.py", "mutacje.json", "ci_lokalnie.py", "serve_centrum", "pytest"))
PENDING = st.sampled_from(("pending", "pass", "PENDING"))


@st.composite
def _ci_query(draw: st.DrawFn) -> tuple[str, tuple[str, ...]]:
    """Zapytanie o CI z docstringu: ``gh pr checks``/``view``, ``gh run view``/``list``, ``gh api`` o status commitu."""

    number = draw(NUMBERS)
    form, arguments = draw(
        st.sampled_from(
            (
                ("gh pr checks {}", (number,)),
                ("gh-axi pr checks {}", (number,)),
                ("gh pr view {} --json {}", (number, "state")),
                ("gh run view {} --json {}", (number, "status")),
                ("gh run list --branch {} --json {}", ("main", "status,conclusion")),
                ("gh api {}", (f"repos/o/r/commits/{number}abc/status",)),
                ("gh api {}", (f"repos/o/r/commits/{number}abc/check-runs",)),
                ("gh api {}", (f"repos/o/r/actions/runs/{number}",)),
            )
        )
    )
    return form, arguments


@st.composite
def _sleep(draw: st.DrawFn) -> tuple[str, tuple[str, ...]]:
    seconds = draw(SECONDS)
    return draw(st.sampled_from((("sleep {}", (seconds,)), (f"perl -e 'select(undef,undef,undef,{seconds})'", ()))))


@st.composite
def _waits(draw: st.DrawFn) -> Template:
    """Czekanie na pierwszym planie, które według docstringu dostaje odmowę."""

    sleep, sleep_arguments = draw(_sleep())
    kind = draw(st.sampled_from(("ci", "pgrep", "watch")))
    if kind == "watch":
        number = draw(NUMBERS)
        form, arguments = draw(
            st.sampled_from(
                (
                    ("gh pr checks {} --watch", (number,)),
                    ("timeout {} gh pr checks {} --watch --interval {}", ("600", number, "30")),
                    ("gh run watch {} --exit-status", (number,)),
                )
            )
        )
        return Template(form, arguments, frozenset({kind}))
    if kind == "pgrep":
        condition = draw(
            st.sampled_from(
                ("until ! pgrep -f {} >/dev/null", "while pgrep -f {} >/dev/null", "until ! pgrep -l -f {}")
            )
        )
        condition_arguments: tuple[str, ...] = (draw(NAMES),)
    else:
        query, query_arguments = draw(_ci_query())
        condition, condition_arguments = draw(
            st.sampled_from(
                (
                    (f"until {query} | grep -q {{}}", (*query_arguments, draw(PENDING))),
                    (f"until ! {query} | grep -q {{}}", (*query_arguments, draw(PENDING))),
                    (f"while {query} | grep -q {{}}", (*query_arguments, draw(PENDING))),
                )
            )
        )
    loop = draw(
        st.sampled_from(
            (
                (f"{condition}; do {sleep}; done", (*condition_arguments, *sleep_arguments)),
                (f"{condition}\ndo\n  {sleep}\ndone", (*condition_arguments, *sleep_arguments)),
            )
        )
    )
    if kind == "ci" and draw(st.booleans()):
        # Licznik prób od 1 z wyjściem z pętli: docstring liczy ``for`` jako czekanie tylko z nimi.
        query, query_arguments = draw(_ci_query())
        counter = draw(st.sampled_from(("$(seq 1 {})", "{{1..{}}}")))
        loop = (
            f"for i in {counter}; do {query} | grep -q {{}} || break; {sleep}; done",
            (draw(SECONDS), *query_arguments, draw(PENDING), *sleep_arguments),
        )
    return Template(loop[0], loop[1], frozenset({kind}))


@st.composite
def _quiet(draw: st.DrawFn) -> Template:
    """Polecenie, które według docstringu przechodzi: zapytanie bez pętli, partia zapytań, czekanie na plik."""

    query, query_arguments = draw(_ci_query())
    sleep, sleep_arguments = draw(_sleep())
    first, second = draw(NUMBERS), draw(NUMBERS)
    form, arguments = draw(
        st.sampled_from(
            (
                (query, query_arguments),
                (f"{query} | grep -c {{}}", (*query_arguments, draw(PENDING))),
                (f"{sleep}; {query}", (*sleep_arguments, *query_arguments)),
                (
                    f"for id in {{}} {{}}; do {sleep}; gh run view $id --json {{}}; done",
                    (first, second, *sleep_arguments, "jobs"),
                ),
                ("for n in {} {}; do gh pr view $n --json {}; done", (first, second, "title")),
                (
                    f"until grep -q {{}} {{}}; do {sleep}; done; tail -5 {{}}",
                    ("DONE", "ci.log", *sleep_arguments, "ci.log"),
                ),
                ("pgrep -fl {}", (draw(NAMES),)),
                ("git status --short", ()),
            )
        )
    )
    return Template(form, arguments, frozenset())


def _templates() -> st.SearchStrategy[Template]:
    return st.one_of(_waits(), _quiet())


def _cases() -> st.SearchStrategy[Case]:
    return _templates().map(lambda template: Case(template.text(), template.refusals))


def _single_quoted(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


WRAPPERS: tuple[Callable[[str], str], ...] = (
    lambda member: f"( {member} )",
    lambda member: f"{{ {member}; }}",
    lambda member: f"x=$( {member} )",
    lambda member: f'echo "$( {member} )"',
    lambda member: f"if true; then {member}; fi",
    lambda member: f"! {member}",
    lambda member: f"bash -c {_single_quoted(member)}",
    lambda member: f"timeout 600 sh -c {_single_quoted(member)}",
)
CONNECTORS = ("; ", " && ", " || ", " | ", "\n")


@st.composite
def _compound(draw: st.DrawFn) -> Case:
    """Polecenie złożone z członów (``;``, ``&&``, ``||``, ``|``, nowa linia, podpowłoka, ``$(…)``, ``-c`` powłoki)."""

    members = draw(st.lists(_cases(), min_size=1, max_size=4))
    wrapped = [
        Case(draw(st.sampled_from(WRAPPERS))(member.text), member.refusals) if draw(st.booleans()) else member
        for member in members
    ]
    text = wrapped[0].text
    for member in wrapped[1:]:
        text += draw(st.sampled_from(CONNECTORS)) + member.text
    return Case(text, frozenset().union(*(member.refusals for member in members)))


PROGRAMS = (
    "echo",
    "printf '%s\\n'",
    "grep -c",
    "grep -nE",
    "rg -n",
    "rg -c",
    "git commit -q -m",
    "git log --grep",
    "jq -n --arg opis",
    "python3 -c",
    "perl -e",
)
LOOP_WORDS = ("until", "while", "for", "do", "done", "sleep", "gh", "pgrep")


@st.composite
def _pattern(draw: st.DrawFn) -> str:
    """Wzorzec wyszukiwania bez spacji ze słowami pętli (``while|until``, ``^(for|done)$``), jak w #446."""

    words = draw(st.lists(st.sampled_from(LOOP_WORDS), min_size=1, max_size=3))
    body = draw(st.sampled_from(("|", "\\|", ";", "&", "!"))).join(words)
    opening, closing = draw(
        st.sampled_from((("", ""), ("(", ")"), ("^(", ")$"), ("\\b", "\\b"), ("{", "}"), ("`", "`")))
    )
    return opening + body + closing


def _quoted_argument(text: str, quote: str) -> str:
    return _single_quoted(text) if quote == "'" else f'"{text}"'


@PROPERTY
@example(text="until ! gh pr checks 1 | grep -q pending; do sleep 30; done", program="grep -c", quote="'", after="")
@example(text="while|until", program="rg -n", quote="'", after="sleep 1; gh pr checks 446")
@example(text="(while)", program="rg -n", quote="'", after="sleep 1; gh pr checks 446")
@example(text="x=$(until ! gh pr checks 1; do sleep 30; done)", program="echo", quote="'", after="")
@given(
    text=st.one_of(_compound().map(lambda case: case.text), _pattern()),
    program=st.sampled_from(PROGRAMS),
    quote=st.sampled_from(("'", '"')),
    # Za argumentem często ``sleep`` i zapytanie o CI: z nimi tekst wzięty za pętlę dostaje odmowę (#446).
    after=st.one_of(st.just(""), st.just("sleep 1; gh pr checks 446"), _quiet().map(lambda template: template.text())),
)
def test_tekst_w_cudzyslowie_jako_argument_polecenia_nie_jest_poleceniem(
    text: str, program: str, quote: str, after: str
) -> None:
    if any(char in text for char in '"$`\\'):
        quote = "'"
    searched = f"{program} {_quoted_argument(text, quote)} wyniki.log"
    command = f"{searched}; {after}" if after else searched

    assert shlex.split(searched) == [*shlex.split(program), text, "wyniki.log"]
    assert czekanie.judge(command, in_background=False) is None


@PROPERTY
@given(template=_templates(), quotes=st.lists(st.sampled_from(("", "'", '"')), max_size=8))
def test_ujecie_argumentu_w_cudzyslow_nie_zmienia_werdyktu(template: Template, quotes: list[str]) -> None:
    bare, quoted = template.text(), template.text(quotes)

    assert shlex.split(quoted) == shlex.split(bare)
    assert _judged(quoted) == _judged(bare) == template.refusals


REDIRECTIONS = (
    "&>/dev/null",
    "&> ci.log",
    "&>>ci.log",
    ">&2",
    "2>&1",
    "> ci.log 2>&1",
    "1>&2",
    "<&0",
    "2>&-",
    ">| ci.log",
    "| tee ci.log",
    "2>&1 | tee -a ci.log",
    "|& tee ci.log",
    "|| echo przerwane",
)


@st.composite
def _loops(draw: st.DrawFn) -> Template:
    return draw(_waits().filter(lambda template: "watch" not in template.refusals))


@st.composite
def _redirected(draw: st.DrawFn) -> tuple[Case, Case]:
    """Ta sama pętla czekania z przekierowaniami za ``done``: na pierwszym planie i puszczona ``&``."""

    loop = draw(_loops())
    redirections = " ".join(draw(st.lists(st.sampled_from(REDIRECTIONS), max_size=3)))
    looped = f"{loop.text()} {redirections}".rstrip()
    after = draw(st.sampled_from(("", "; gh pr checks 1", " && echo koniec", "\necho koniec")))
    in_background = draw(st.sampled_from((" &", "&", " & W=$!", " &\necho w tle")))
    return Case(looped + after, loop.refusals), Case(looped + in_background, frozenset())


@PROPERTY
@example(
    cases=(
        Case("until ! gh pr checks 1; do sleep 30; done &>/dev/null", frozenset({"ci"})),
        Case("until ! gh pr checks 1; do sleep 30; done &>/dev/null &", frozenset()),
    )
)
@given(cases=_redirected())
def test_przekierowanie_za_petla_to_nie_tlo_a_pętla_puszczona_ampersandem_przechodzi(cases: tuple[Case, Case]) -> None:
    foreground, background = cases

    assert _verdict_matches(foreground), foreground.text
    assert _verdict_matches(background), background.text


@PROPERTY
# Skrypt ``-c`` powłoki w apostrofach to polecenie, a nie literał (#496).
@example(case=Case("bash -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'", frozenset({"ci"})))
@example(case=Case("echo a; timeout 600 sh -c 'until ! pgrep -f bench.py; do sleep 5; done'", frozenset({"pgrep"})))
@given(case=_compound())
def test_polecenie_zlozone_dostaje_werdykt_najgorszego_czlonu(case: Case) -> None:
    assert _verdict_matches(case), case.text
    assert czekanie.judge(case.text, in_background=True) is None


def _bash_4() -> str | None:
    bash = shutil.which("bash")
    if bash is None or sys.platform == "win32":
        return None
    version = subprocess.run([bash, "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True, check=True)
    return bash if int(version.stdout) >= 4 else None


@pytest.mark.skipif(_bash_4() is None, reason="bez bash 4 (|& i &>>), np. /bin/bash 3.2 na Macu i Windows")
@settings(derandomize=True, database=None, deadline=None, max_examples=60)
@given(
    case=st.one_of(_compound(), _redirected().map(lambda cases: cases[0]), _redirected().map(lambda cases: cases[1]))
)
def test_wygenerowane_polecenia_sa_poprawne_dla_basha(case: Case) -> None:
    bash = _bash_4()
    assert bash is not None

    checked = subprocess.run([bash, "-n", "-c", case.text], capture_output=True, text=True, check=False)

    assert checked.returncode == 0, (case.text, checked.stderr)


TIMER = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("czekanie", sys.argv[1])
hook = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = hook
spec.loader.exec_module(hook)
for command in json.load(sys.stdin):
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        hook.judge(command, False)
        best = min(best, time.perf_counter() - start)
    print(best)
"""
# Wejście 16 razy dłuższe: czas liniowy rośnie ok. 16 razy, a kwadratowy ok. 256 razy.
GROWTH = 16
LINEAR_LIMIT = GROWTH * 4
# Tylko na zawieszenie (wzorzec wykładniczy): werdykt daje stosunek czasów, a nie ten limit.
HANG_S = 30
FRAGMENTS = (
    "'",
    '"',
    "(",
    ")",
    "$(",
    '"$(',
    "`",
    "\\",
    "{",
    "}",
    " ",
    "\n",
    ";",
    "&",
    "|",
    "2>&1 ",
    "2>1 ",
    "&>",
    "until x; do ",
    "while x; do ",
    "for x in y; do ",
    "done; ",
    "done",
    "do ",
    "sleep 1; ",
    "gh pr checks 1 ",
    "gh api x ",
    "check-runs ",
    "--watch ",
    "pgrep -a ",
    "pgrep -f x ",
    "bash -c ",
    "-c ",
    "<<EOF\n",
    "EOF\n",
    "break ",
    "$(seq 1 ",
    "{1..",
    "x",
    "a b",
)
PREFIXES = ("", "until x; do sleep 1; ", "while :; do sleep 1; gh pr checks 1; done ", "echo '", 'echo "')


# Bez zmniejszania przykładu: na kodzie kwadratowym każda próba zmniejszenia czekałaby do ``HANG_S``.
@settings(derandomize=True, database=None, deadline=None, max_examples=30, phases=(Phase.explicit, Phase.generate))
# Dawne regresje: wzorzec wykładniczy po ``done`` (#446 runda 2), pętle bez końca, puste wiersze, ``gh pr checks``
# i ``gh api`` czytane do końca polecenia, ``"$(`` głębiej niż stos Pythona.
@example(prefix="while :; do sleep 1; gh pr checks 1; done ", unit="2>1 ")
@example(prefix="", unit="until x; do ")
@example(prefix="", unit="until a& do b& done& ")
@example(prefix="", unit="\n")
@example(prefix="", unit="gh pr checks 1 ")
@example(prefix="until x; do sleep 1; ", unit="gh api x ")
@example(prefix="", unit='"$(')
@given(prefix=st.sampled_from(PREFIXES), unit=st.lists(st.sampled_from(FRAGMENTS), min_size=1, max_size=3).map("".join))
def test_czas_werdyktu_rosnie_najwyzej_liniowo_z_dlugoscia_polecenia(prefix: str, unit: str) -> None:
    repeats = -(-4000 // len(unit))
    commands = [prefix + unit * repeats, prefix + unit * repeats * GROWTH]

    timed = subprocess.run(
        [sys.executable, "-c", TIMER, str(CZEKANIE)],
        input=json.dumps(commands),
        capture_output=True,
        text=True,
        check=True,
        timeout=HANG_S,
    )
    short, long = (float(line) for line in timed.stdout.split())

    assert long / max(short, 1e-6) <= LINEAR_LIMIT, (short, long)


MODES = st.one_of(
    st.none(),
    st.sampled_from(("default", "acceptEdits", "plan", "dontAsk", "auto", "bypassPermissions")),
    st.text(max_size=20),
)
SWAPPED_QUOTES = str.maketrans({"'": '"', '"': "'"})


@PROPERTY
@given(mode=MODES, command=st.one_of(_compound().map(lambda case: case.text), st.text()))
def test_zgoda_rozstrzyga_sam_tryb_a_nie_tekst_polecenia(mode: str | None, command: str) -> None:
    # Docstring zgoda.py: kiedy pytać, rozstrzyga kontrola Claude Code, a hook jej nie odtwarza (wariant A z #496).
    denied = {"behavior": "deny", "message": zgoda.MESSAGE}
    refusal = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": denied}}
    expected = refusal if mode == "bypassPermissions" else None

    for text in (command, command.translate(SWAPPED_QUOTES), f"sh -c {_single_quoted(command)}"):
        tool_input = {"command": text, "description": "x"}
        event = {
            "hook_event_name": "PermissionRequest",
            "permission_mode": mode,
            "tool_name": "Bash",
            "tool_input": tool_input,
        }

        assert zgoda.decision(event) == expected


@PROPERTY
@example(stdin=b"[" * 100000)
@example(stdin=b'{"permission_mode": "bypassPermissions"')
@given(
    stdin=st.one_of(
        st.binary(),
        st.text().map(str.encode),
        st.builds(lambda depth, opening: opening * depth, st.integers(1, 200000), st.sampled_from((b"[", b'{"a":'))),
    )
)
def test_zgoda_na_nieczytelnym_wejsciu_konczy_sie_kodem_0_bez_odpowiedzi(stdin: bytes) -> None:
    printed = io.StringIO()
    with mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin))), redirect_stdout(printed):
        code = zgoda.main()

    assert (code, printed.getvalue()) == (0, "")
