"""Sprawdza model TLA+ Aktualizacji narzędzia przy każdej kolejności awarii (TLC).

Uruchamia TLC na każdej konfiguracji z ``model/*.cfg``, porównuje wynik z
``model/oczekiwane.json`` i opowiada każdy kontrprzykład krokami kodu. Javy nie
trzeba mieć w systemie: przypięte ``jdk4py`` i ``tla2tools.jar`` trafiają raz do
``.verification/formal-aktualizacja`` (ignorowanego przez Gita). Na końcu
ostrzega, gdy pokryty kod zmienił się od commitu synchronizacji z ``SKILL.md``.

    .venv/bin/python .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
    py -3 .agents\\skills\\verify-aktualizacja-narzedzia\\scripts\\sprawdz_aktualizacje.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[2]
MODEL = SKILL / "model"
SPEC = "AktualizacjaNarzedzia.tla"
CACHE = ROOT / ".verification" / "formal-aktualizacja"

JDK4PY = "jdk4py==25.0.2.1"
TLA_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
TLA_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"

PASSES, VIOLATES = "przechodzi", "narusza"
_STATE = re.compile(r"^State \d+: ")
_VARIABLE = re.compile(r"^/\\ (\w+) = (.*)$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None
    )
    parser.add_argument(
        "--config",
        action="append",
        help="Tylko ta konfiguracja (nazwa pliku .cfg bez rozszerzenia).",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Znane znaleziska też kończą się kodem 1."
    )
    args = parser.parse_args(argv)

    expected = json.loads((MODEL / "oczekiwane.json").read_text(encoding="utf-8"))
    names = args.config or sorted(path.stem for path in MODEL.glob("*.cfg"))
    java, jar = _java(), _tla_tools()

    all_known = frozenset(
        entry["wybacz"] for entry in expected.values() if "wybacz" in entry
    )
    new, gone, known, broken = [], [], [], []
    for name in names:
        want = expected.get(name, {})
        print(f"\n== {name}: {_description(name)}")
        if want.get("wynik") != VIOLATES:
            verdict = _run(java, jar, name, frozenset())
            print(f"   wynik: {verdict}, oczekiwany: {PASSES}")
            if verdict is None:
                broken.append(name)
            elif verdict == VIOLATES:
                new.append(name)
            continue
        # TLC kończy na pierwszym kontrprzykładzie, więc każde znane znalezisko ma dwa przebiegi:
        # bez pozostałych znanych (czy ono dalej jest) i bez wszystkich znanych (czy nic poza nimi).
        finding = want["wybacz"]
        print(f"   znane znalezisko „{finding}”: {want['znalezisko']}")
        own = _run(java, jar, name, all_known - {finding})
        print(f"   wynik: {own}, oczekiwany: {VIOLATES}")
        if own is None:
            broken.append(name)
            continue
        if own == PASSES:
            gone.append(name)
            print(
                "   znalezisko zniknęło: opisz zmianę w SKILL.md i zmień „wynik” w model/oczekiwane.json."
            )
        print("   reszta przebiegów, bez wszystkich znanych znalezisk:")
        rest = _run(java, jar, name, all_known)
        print(f"   wynik: {rest}, oczekiwany: {PASSES}")
        if rest is None:
            broken.append(name)
        elif rest == VIOLATES:
            new.append(name)
        elif own == VIOLATES:
            known.append(name)

    _warn_about_drift()
    print()
    if broken:
        print(f"AKTUALIZACJA: BŁĄD MODELU ({len(broken)})")
        return 2
    if new or gone:
        parts = [
            f"NOWE NARUSZENIE ({len(new)})" if new else "",
            f"ZNALEZISKO ZNIKNĘŁO ({len(gone)})" if gone else "",
        ]
        print("AKTUALIZACJA: " + ", ".join(part for part in parts if part))
        return 1
    if known:
        print(f"AKTUALIZACJA OK, ZNANE ZNALEZISKA: {len(known)}")
        return 1 if args.strict else 0
    print("AKTUALIZACJA OK")
    return 0


def _java() -> str:
    """Java z przypiętego ``jdk4py`` w katalogu podręcznym; instaluje je za pierwszym razem."""

    target = CACHE / "jdk"
    if not (target / "jdk4py").is_dir():
        shutil.rmtree(target, ignore_errors=True)
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
        ]
        if (
            subprocess.run(
                [sys.executable, "-m", "pip", "--version"], capture_output=True
            ).returncode
            != 0
        ):
            uv = shutil.which("uv")
            if uv is None:
                sys.exit(
                    "BŁĄD: ten Python nie ma pip, a uv nie jest dostępne; nie da się zainstalować jdk4py."
                )
            command = [uv, "pip", "install", "--python", sys.executable, "--quiet"]
        subprocess.run([*command, "--target", str(target), JDK4PY], check=True)
    found = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(target)!r}); import jdk4py; print(jdk4py.JAVA)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return found.stdout.strip()


def _tla_tools() -> Path:
    """``tla2tools.jar`` w przypiętej wersji, sprawdzony sumą SHA-256."""

    jar = CACHE / "tla2tools-1.7.4.jar"
    if not jar.is_file() or _sha256(jar) != TLA_SHA256:
        CACHE.mkdir(parents=True, exist_ok=True)
        partial = jar.with_suffix(".part")
        with (
            urllib.request.urlopen(TLA_URL, timeout=120) as response,
            partial.open("wb") as file,
        ):
            shutil.copyfileobj(response, file)
        if _sha256(partial) != TLA_SHA256:
            partial.unlink()
            sys.exit(f"BŁĄD: {TLA_URL} ma inną sumę SHA-256 niż przypięta.")
        os.replace(partial, jar)
    return jar


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(java: str, jar: Path, name: str, forgiven: frozenset[str]) -> str | None:
    """Werdykt TLC dla konfiguracji ``name``, z opowiedzianym kontrprzykładem; ``None`` przy błędzie modelu.

    ``forgiven`` to znane znaleziska z ``model/oczekiwane.json``; gdy są, przebieg
    sprawdza ``TataMaDzialajacaWersjePozaZnanymi`` z ``Wybaczone`` równym im.
    """

    config = (MODEL / f"{name}.cfg").read_text(encoding="utf-8")
    if forgiven:
        tags = ", ".join(f'"{tag}"' for tag in sorted(forgiven))
        config = config.replace(
            " TataMaDzialajacaWersje\n", " TataMaDzialajacaWersjePozaZnanymi\n"
        )
        config = config.replace("Wybaczone = {}", f"Wybaczone = {{{tags}}}")
    # TLC zapisuje ślady i stany obok specyfikacji, więc działa na kopii w katalogu tymczasowym.
    with tempfile.TemporaryDirectory(prefix="tlc-") as work:
        shutil.copy2(MODEL / SPEC, work)
        Path(work, f"{name}.cfg").write_text(config, encoding="utf-8")
        result = subprocess.run(
            [
                java,
                "-XX:+UseParallelGC",
                "-cp",
                str(jar),
                "tlc2.TLC",
                "-workers",
                "auto",
                "-metadir",
                str(Path(work, "stany")),
                "-config",
                f"{name}.cfg",
                SPEC,
            ],
            cwd=work,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    output = result.stdout + result.stderr
    if "No error has been found" in output:
        return PASSES
    invariant = _violated(output)
    if invariant is None:
        print("   BŁĄD MODELU: TLC nie dał werdyktu.\n" + output)
        return None
    _tell(_trace(output))
    if invariant == "TypeOK":
        print(
            "   BŁĄD MODELU: naruszony TypeOK, czyli model wyszedł poza swoje wartości."
        )
        return None
    return VIOLATES


def _violated(output: str) -> str | None:
    found = re.search(r"Invariant (\w+) is violated", output)
    return found.group(1) if found else None


def _trace(output: str) -> list[dict[str, str]]:
    states: list[dict[str, str]] = []
    for line in output.splitlines():
        if _STATE.match(line):
            states.append({})
        elif states and (variable := _VARIABLE.match(line.strip())):
            states[-1][variable.group(1)] = variable.group(2).strip('"')
    return states


def _tell(trace: list[dict[str, str]]) -> None:
    first, last = trace[0], trace[-1]
    yes = {"TRUE": "tak", "FALSE": "nie"}
    print(
        "   nowa wersja: usuwa plik taty z config/: {}, zmienia requirements.txt: {}, startuje: {}".format(
            yes[first["nowaUsuwaPlikTaty"]],
            yes[first["nowaZmieniaWymagania"]],
            yes[first["nowaStartuje"]],
        )
    )
    for number, state in enumerate(trace[1:], start=1):
        print(f"   {number}. {state['krok']}")
    print(
        f"   na koniec: klon na wersji {last['head']}, plik taty: {last['plikTaty']}, "
        f"biblioteki: {last['biblioteki']}, Centrum: {last['centrum']}"
    )


def _description(name: str) -> str:
    first = (MODEL / f"{name}.cfg").read_text(encoding="utf-8").splitlines()[0]
    return first.removeprefix("\\*").strip()


def _warn_about_drift() -> None:
    """Ostrzega, gdy plik z tabeli pokrycia w SKILL.md zmienił się od commitu synchronizacji."""

    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    sync = re.search(r"Sync commit: `([0-9a-f]{7,40})`", text)
    covered = sorted(set(re.findall(r"`(src/rozliczenia/[\w/]+\.py)`", text)))
    if sync is None or not covered:
        print("\nUWAGA: SKILL.md nie ma commitu synchronizacji albo tabeli pokrycia.")
        return
    diff = subprocess.run(
        ["git", "diff", "--name-only", sync.group(1), "--", *covered],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        print(
            f"\nUWAGA: commitu synchronizacji {sync.group(1)} nie ma w tej historii; porównaj pokryty kod ręcznie."
        )
    elif diff.stdout.strip():
        changed = ", ".join(diff.stdout.split())
        print(
            f"\nUWAGA: pokryty kod zmienił się od {sync.group(1)}: {changed}. Sprawdź, czy model dalej go opisuje."
        )


if __name__ == "__main__":
    raise SystemExit(main())
