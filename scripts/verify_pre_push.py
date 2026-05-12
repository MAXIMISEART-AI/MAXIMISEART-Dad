"""Pre-push verifier for MAXIMISEART-Dad."""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TATA_WORDS = ["Claude", "Anthropic", "OpenAI", "AI", "LLM"]
SECRET_PATTERNS = [
    ".env",
    ".env.local",
    ".env.*.local",
    "*oauth-token*.json",
    "*client_secret*.json",
    "*credentials*.json",
    "*.xlsx",
    "*.xlsm",
    "*.xlsb",
    "*.xls",
    "runtime/*",
    "vault/*",
    "reports/*",
    "state/*",
    "learning/*",
    "logs/*",
    "*.log",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="verify_pre_push")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-github", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures: list[str] = []

    if not args.skip_tests and not run_tests():
        failures.append("pytest failed")

    secret_hits = find_tracked_secret_hits()
    if secret_hits:
        failures.append("tracked runtime/secret files: " + ", ".join(secret_hits))

    forbidden_hits = find_forbidden_tata_words()
    if forbidden_hits:
        failures.append("forbidden tata-facing words: " + ", ".join(forbidden_hits))

    if not args.skip_github:
        remote_ok, remote_msg = check_github_remote()
        if not remote_ok:
            failures.append(remote_msg)
        else:
            print(remote_msg)

    if failures:
        print("PRE_PUSH_VERIFY: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PRE_PUSH_VERIFY: PASS")
    return 0


def run_tests() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--basetemp", ".pytest-tmp\\verify-pre-push"],
        cwd=str(PROJECT_ROOT),
        text=True,
    )
    return result.returncode == 0


def find_tracked_secret_hits() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if tracked.returncode != 0:
        return ["git ls-files failed"]
    hits = []
    for raw in tracked.stdout.splitlines():
        path = raw.replace("\\", "/")
        if any(fnmatch.fnmatch(path, pattern) for pattern in SECRET_PATTERNS):
            hits.append(raw)
    return hits


def find_forbidden_tata_words() -> list[str]:
    files = [PROJECT_ROOT / "README.md", *sorted((PROJECT_ROOT / "docs").glob("*.md"))]
    pattern = re.compile(r"\b(" + "|".join(re.escape(word) for word in FORBIDDEN_TATA_WORDS) + r")\b")
    hits = []
    for path in files:
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = pattern.search(line)
            if match:
                hits.append(f"{path.relative_to(PROJECT_ROOT)}:{line_no}:{match.group(1)}")
    return hits


def check_github_remote() -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return False, "origin remote is not configured"

    url = result.stdout.strip()
    if "MAXIMISEART-DAD" not in url.upper():
        return False, f"origin remote does not point to MAXIMISEART-DAD: {url}"

    return True, f"GitHub remote OK: {url}"


if __name__ == "__main__":
    sys.exit(main())
