"""Init wizard deployment-ready configuration tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_configure_writes_env_without_runtime_secrets(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    runtime = tmp_path / "runtime"
    vault = runtime / "vault"
    excel = tmp_path / "tata.xlsx"
    excel.write_bytes(b"placeholder")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/init_wizard.py",
            "--configure",
            "--env",
            str(env_path),
            "--runtime-path",
            str(runtime),
            "--vault-path",
            str(vault),
            "--excel-path",
            str(excel),
            "--run-time",
            "07:15",
            "--skip-oauth",
            "--no-test-run",
            "--no-install-task",
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    content = env_path.read_text(encoding="utf-8")
    assert f"DAD_RUNTIME_PATH={runtime}" in content
    assert f"DAD_VAULT_PATH={vault}" in content
    assert f"DAD_EXCEL_PATH={excel}" in content
    assert "DAD_RUN_TIME=07:15" in content
    assert "DAD_USE_REAL_API=false" in content
    assert "oauth-token" in content
    assert "client_secret" not in content
    assert "ANTHROPIC" not in content
    assert "OPENAI" not in content
