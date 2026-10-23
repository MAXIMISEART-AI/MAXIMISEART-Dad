"""Kontrakt wywołania skryptów skilli w testach: ``tools/skrypt_skilla.py`` leży poza pakietem."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import skrypt_skilla  # noqa: E402

__all__ = ["skrypt_skilla"]
