"""Run the complete disposable verification workflow as one command."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tomllib
from typing import TextIO
import uuid


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[4]
PERIOD = "08_14_09_2026"
TIMEOUT_SECONDS = 120
PYTHON_COMMAND = (sys.executable,)


class VerificationFailure(RuntimeError):
    """A workflow step failed its expected contract."""


def _display_command(arguments: list[str]) -> str:
    return shlex.join([*PYTHON_COMMAND, *arguments])


def _decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _echo(text: str, stream: TextIO) -> None:
    if not text:
        return
    try:
        stream.write(text)
        stream.flush()
    except UnicodeEncodeError:
        stream.buffer.write(text.encode("utf-8"))
        stream.flush()


def _write_step_evidence(
    evidence_path: Path,
    arguments: list[str],
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
    launch_error: str | None = None,
) -> None:
    sections = [f"command: {_display_command(arguments)}", "stdout:", stdout]
    sections.extend(["stderr:", stderr])
    if launch_error is not None:
        sections.extend(["launch_error:", launch_error])
    if exit_code is not None:
        sections.append(f"exit_code={exit_code}")
    evidence_path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")


def _run_step(
    name: str,
    arguments: list[str],
    evidence_root: Path,
    environment: dict[str, str],
    *,
    expected_exit: int,
) -> None:
    evidence_path = evidence_root / f"{name}.txt"
    try:
        completed = subprocess.run(
            [*PYTHON_COMMAND, *arguments],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decode(exc.stdout)
        stderr = _decode(exc.stderr)
        _write_step_evidence(
            evidence_path,
            arguments,
            stdout=stdout,
            stderr=stderr,
            launch_error=f"timed out after {TIMEOUT_SECONDS} seconds",
        )
        _echo(stdout, sys.stdout)
        _echo(stderr, sys.stderr)
        raise VerificationFailure(f"{name} timed out") from exc
    except OSError as exc:
        _write_step_evidence(evidence_path, arguments, launch_error=str(exc))
        raise VerificationFailure(f"{name} could not start: {exc}") from exc

    stdout = _decode(completed.stdout)
    stderr = _decode(completed.stderr)
    _write_step_evidence(
        evidence_path,
        arguments,
        stdout=stdout,
        stderr=stderr,
        exit_code=completed.returncode,
    )
    _echo(stdout, sys.stdout)
    _echo(stderr, sys.stderr)
    if completed.returncode != expected_exit:
        raise VerificationFailure(
            f"{name} returned {completed.returncode}; expected {expected_exit}"
        )


def _version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def _new_paths() -> tuple[Path, Path]:
    run_parent = REPO_ROOT / ".verification" / "runs"
    evidence_parent = REPO_ROOT / ".verification" / "evidence"
    run_parent.mkdir(parents=True, exist_ok=True)
    evidence_parent.mkdir(parents=True, exist_ok=True)
    run_id = f"rozliczenia-{uuid.uuid4().hex}"
    evidence_root = evidence_parent / run_id
    evidence_root.mkdir()
    return run_parent / run_id, evidence_root


def _create_lock(run_root: Path) -> None:
    placeholder = run_root / "placeholder.xlsx"
    placeholder.with_name(f"~${placeholder.name}").touch()


def _create_existing_output(run_root: Path) -> None:
    target_directory = run_root / PERIOD / f"Rozliczenie pracowników {PERIOD}"
    target_directory.mkdir()
    (target_directory / "existing-synthetic.txt").write_text("preserve", encoding="utf-8")


def _run_workflow(variant: str, run_root: Path, evidence_root: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    version = _version()
    source = run_root / PERIOD / f"Rozliczenie {PERIOD} - zbiorcze.xlsx"
    config = run_root / "worker_mapping.yaml"
    metrics = run_root / "metrics.jsonl"
    helper_directory = Path(".agents") / "skills" / "verify-rozliczenia" / "scripts"

    fixture_arguments = [str(helper_directory / "create_fixture.py"), "--root", str(run_root)]
    if variant == "unmapped":
        fixture_arguments.append("--include-unmapped")
    _run_step("fixture", fixture_arguments, evidence_root, environment, expected_exit=0)

    _run_step(
        "doctor",
        [str(helper_directory / "doctor.py"), "--root", str(run_root), "--expected-version", version],
        evidence_root,
        environment,
        expected_exit=0,
    )

    dry_assert_arguments = [
        str(helper_directory / "assert_results.py"),
        "--root",
        str(run_root),
        "--expect",
        "dry-run",
        "--transcript",
        str(evidence_root / "dry-run.txt"),
    ]

    _run_step(
        "dry-run",
        [
            "run.py",
            "--source",
            str(source),
            "--config",
            str(config),
            "--placeholder",
            str(run_root / "placeholder.xlsx"),
            "--metrics",
            str(metrics),
            "--dry-run",
        ],
        evidence_root,
        environment,
        expected_exit=2 if variant == "unmapped" else 0,
    )
    _run_step("assert-dry-run", dry_assert_arguments, evidence_root, environment, expected_exit=0)

    if variant == "existing":
        _create_existing_output(run_root)
    elif variant == "locked":
        _create_lock(run_root)

    _run_step(
        "run",
        [
            "run.py",
            "--source",
            str(source),
            "--config",
            str(config),
            "--placeholder",
            str(run_root / "placeholder.xlsx"),
            "--metrics",
            str(metrics),
        ],
        evidence_root,
        environment,
        expected_exit=0 if variant == "default" else 1,
    )
    shutil.copy2(metrics, evidence_root / "metrics.jsonl")

    run_expectation = {
        "default": "run",
        "existing": "existing-output",
        "locked": "no-publish",
        "unmapped": "no-publish",
    }[variant]
    run_assert_arguments = [
        str(helper_directory / "assert_results.py"),
        "--root",
        str(run_root),
        "--expect",
        run_expectation,
        "--transcript",
        str(evidence_root / "run.txt"),
    ]
    if variant == "unmapped":
        run_assert_arguments.extend(["--expected-message", "WYKONAWCA bez mapowania"])
    elif variant == "locked":
        run_assert_arguments.extend(["--expected-message", "Placeholder jest otwarty lub zablokowany"])
    _run_step("assert-run", run_assert_arguments, evidence_root, environment, expected_exit=0)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("default", "existing", "locked", "unmapped"), default="default")
    args = parser.parse_args(argv)

    run_root, evidence_root = _new_paths()
    failure: BaseException | None = None
    cleanup_failure: BaseException | None = None
    try:
        _run_workflow(args.variant, run_root, evidence_root)
    except Exception as exc:
        failure = exc
    finally:
        cleanup_environment = os.environ.copy()
        cleanup_environment["PYTHONUTF8"] = "1"
        cleanup_environment["PYTHONIOENCODING"] = "utf-8"
        try:
            _run_step(
                "cleanup",
                [
                    str(Path(".agents") / "skills" / "verify-rozliczenia" / "scripts" / "cleanup.py"),
                    "--root",
                    str(run_root),
                ],
                evidence_root,
                cleanup_environment,
                expected_exit=0,
            )
        except BaseException as exc:
            cleanup_failure = exc

    if failure is not None or cleanup_failure is not None:
        details = [f"workflow={failure}" if failure else "workflow=ok"]
        details.append(f"cleanup={cleanup_failure}" if cleanup_failure else "cleanup=ok")
        print(f"VERIFY FAIL | variant={args.variant} | evidence={evidence_root} | " + "; ".join(details), file=sys.stderr)
        return 1
    if run_root.exists():
        print(f"VERIFY FAIL | scratch root remains: {run_root}", file=sys.stderr)
        return 1
    required = {
        "fixture.txt",
        "doctor.txt",
        "dry-run.txt",
        "assert-dry-run.txt",
        "run.txt",
        "assert-run.txt",
        "cleanup.txt",
        "metrics.jsonl",
    }
    missing = sorted(name for name in required if not (evidence_root / name).is_file())
    if missing:
        print(f"VERIFY FAIL | missing evidence: {', '.join(missing)}", file=sys.stderr)
        return 1

    self_test_environment = os.environ.copy()
    self_test_environment["PYTHONUTF8"] = "1"
    self_test_environment["PYTHONIOENCODING"] = "utf-8"
    try:
        _run_step(
            "self-test",
            [
                str(Path(".agents") / "skills" / "verify-rozliczenia" / "scripts" / "self_test.py"),
                "--evidence-root",
                str(evidence_root),
            ],
            evidence_root,
            self_test_environment,
            expected_exit=0,
        )
    except BaseException as exc:
        print(f"VERIFY FAIL | self-test={exc} | evidence={evidence_root}", file=sys.stderr)
        return 1

    required.add("self-test.txt")
    missing = sorted(name for name in required if not (evidence_root / name).is_file())
    if missing:
        print(f"VERIFY FAIL | missing evidence: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"VERIFY OK | variant={args.variant} | evidence={evidence_root} | scratch_removed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
