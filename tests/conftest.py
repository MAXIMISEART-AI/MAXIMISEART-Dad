"""pytest conftest — shared fixtures dla MAXIMISEART-Dad testów."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def sample_emails() -> list[dict]:
    """Load wszystkie JSON emails z fixtures/sample_emails/."""
    emails = []
    for path in sorted((FIXTURES_DIR / "sample_emails").glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            emails.append(json.load(f))
    return emails


@pytest.fixture
def test_output_dir(tmp_path: Path) -> Path:
    """Tymczasowy output dir dla test writes (gitignored)."""
    out = tmp_path / "dad-test-output"
    out.mkdir(parents=True, exist_ok=True)
    return out
