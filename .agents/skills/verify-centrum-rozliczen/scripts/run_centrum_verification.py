"""One-command proof of Centrum rozliczeń: fixture, launch, doctor, drive in Chromium, cleanup, self-test.

Prints ``VERIFY OK | features=… | evidence=… | scratch_removed=true`` or
``VERIFY FAIL | …``. Scratch lives in ``.verification/runs/centrum-<id>`` and is
removed; evidence lives in ``.verification/evidence/centrum-<id>`` and is kept.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[3]
STEP_TIMEOUT_SECONDS = 300
REQUIRED_EVIDENCE = (
    "fixture.txt",
    "server.txt",
    "doctor.txt",
    "drive.txt",
    "cleanup.txt",
    "self-test.txt",
)
REQUIRED_SCREENSHOTS = {
    "ustawienia": (
        "01-ustawienia-pusty-stan.png",
        "02-ustawienia-folder-okresow.png",
        "03-ustawienia-rejestr-zlecen.png",
        "04-ustawienia-brak-rejestru.png",
        "05-ustawienia-motyw-jasny.png",
    ),
    "tablica-okresow": (
        "06-tablica-okresow.png",
        "07-tablica-otwieranie.png",
        "08-tablica-po-zmianie-na-dysku.png",
        "09-tablica-podpowiedz.png",
    ),
    "konfiguracja": (
        "10-konfiguracja-gotowa.png",
        "11-konfiguracja-tylko-do-odczytu.png",
        "12-konfiguracja-wzorzec-otwarty.png",
        "13-konfiguracja-brak-wzorca.png",
        "14-konfiguracja-nieczytelna-konfiguracja-wykonawcow.png",
    ),
    "metryki": (
        "20-metryki-karty-okresow.png",
        "21-metryki-wykres.png",
        "22-metryki-tabela-etapow.png",
        "23-metryki-za-malo-obserwacji.png",
        "24-metryki-historia.png",
        "25-metryki-historia-filtry.png",
        "26-metryki-nowy-rekord-z-cli.png",
        "27-metryki-pusty-stan.png",
    ),
}


class VerificationFailure(Exception):
    pass


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _run_step(name: str, arguments: list[str], evidence: Path) -> None:
    command = [sys.executable, *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=STEP_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        (evidence / f"{name}.txt").write_text(f"command: {command}\ntimed out\n", encoding="utf-8")
        raise VerificationFailure(f"{name} timed out") from exc
    (evidence / f"{name}.txt").write_text(
        f"command: {command}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}\nexit_code={completed.returncode}\n",
        encoding="utf-8",
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise VerificationFailure(f"{name} returned {completed.returncode}")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _launch(run_root: Path, evidence: Path) -> tuple[subprocess.Popen[bytes], str]:
    log = (evidence / "server.txt").open("wb")
    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS / "serve_centrum.py"), "--root", str(run_root), "--port", str(_free_port())],
        cwd=REPO_ROOT,
        env=_environment(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 30
    server_file = run_root / "server.json"
    while True:
        if process.poll() is not None:
            raise VerificationFailure(f"Centrum exited with {process.returncode} before it was ready; see server.txt")
        if server_file.exists():
            url = str(json.loads(server_file.read_text(encoding="utf-8"))["url"])
            try:
                with urllib.request.urlopen(url + "api/health", timeout=2):
                    return process, url
            except OSError:
                pass
        if time.monotonic() > deadline:
            raise VerificationFailure("Centrum was not ready within 30 seconds; see server.txt")
        time.sleep(0.1)


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Stop exactly the server process this run started."""

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _preflight() -> None:
    if not (REPO_ROOT / "src" / "rozliczenia" / "centrum" / "static" / "index.html").exists():
        raise VerificationFailure("the built frontend is missing; run `npm ci && npm run build` in frontend/")
    if importlib.util.find_spec("playwright") is None:
        raise VerificationFailure(
            "Playwright for Python is missing; run `pip install playwright` and `python -m playwright install chromium`"
        )


def _verify(feature: str) -> Path:
    run_root = REPO_ROOT / ".verification" / "runs" / f"centrum-{uuid.uuid4().hex}"
    evidence = REPO_ROOT / ".verification" / "evidence" / run_root.name
    evidence.mkdir(parents=True)
    print(f"EVIDENCE {evidence}", flush=True)
    process: subprocess.Popen[bytes] | None = None
    try:
        _preflight()
        _run_step("fixture", [str(SCRIPTS / "create_centrum_fixture.py"), "--root", str(run_root)], evidence)
        process, url = _launch(run_root, evidence)
        _run_step("doctor", [str(SCRIPTS / "centrum_doctor.py"), "--root", str(run_root)], evidence)
        _run_step(
            "drive",
            [str(SCRIPTS / "drive_centrum.py"), "--root", str(run_root), "--url", url,
             "--evidence", str(evidence), "--feature", feature],
            evidence,
        )
    finally:
        if process is not None:
            _stop(process)
        _run_step("cleanup", [str(SCRIPTS / "centrum_cleanup.py"), "--root", str(run_root)], evidence)
    if run_root.exists():
        raise VerificationFailure(f"scratch was not removed: {run_root}")
    features = REQUIRED_SCREENSHOTS if feature == "all" else {feature: REQUIRED_SCREENSHOTS[feature]}
    missing = [name for name in REQUIRED_EVIDENCE[:-1] if not (evidence / name).exists()]
    missing += [shot for shots in features.values() for shot in shots if not (evidence / "screenshots" / shot).exists()]
    if missing:
        raise VerificationFailure(f"evidence is missing: {', '.join(missing)}")
    _run_step("self-test", [str(SCRIPTS / "centrum_self_test.py"), "--evidence-root", str(evidence)], evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feature", choices=("all", *REQUIRED_SCREENSHOTS), default="all")
    args = parser.parse_args(argv)
    try:
        evidence = _verify(args.feature)
    except VerificationFailure as exc:
        print(f"VERIFY FAIL | features={args.feature} | {exc}", file=sys.stderr)
        return 1
    print(f"VERIFY OK | features={args.feature} | evidence={evidence} | scratch_removed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
