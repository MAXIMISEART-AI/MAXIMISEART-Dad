"""Plugin pytest dla ``tools/mutacje_zmiany.py``: które testy wykonują które zmienione linie.

``tools/mutacje_zmiany.py`` uruchamia testy z ``-p pokrycie_linii`` i ze zmienną ``POKRYCIE_LINII``: JSON
``{"linie": {ścieżka bezwzględna: [numery linii]}, "wynik": katalog}``. Każdy proces pytest (także worker xdist)
zapisuje w katalogu ``wynik`` plik ``<pid>.json`` z ``{nodeid testu: {ścieżka: [linie]}}``. Liczy się kod
wykonany w procesie testów, także w jego wątkach, a nie w procesach, które test uruchamia. Linia wykonana poza
testem (przy imporcie modułu w czasie zbierania testów) nie należy do żadnego testu.
"""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import threading
from types import CodeType, FrameType
from typing import Any

import pytest

VARIABLE = "POKRYCIE_LINII"


class _Recorder:
    def __init__(self, lines: dict[str, set[int]]) -> None:
        self.lines = lines
        self.test: str | None = None
        self.hits: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))

    def hit(self, path: str, line: int) -> bool:
        """Zapisuje linię bieżącego testu; fałsz, gdy linia nie jest zmieniona i nie trzeba jej więcej śledzić."""

        if line not in self.lines.get(path, ()):
            return False
        if self.test is not None:
            self.hits[self.test][path].add(line)
        return True


def _start(recorder: _Recorder) -> None:
    monitoring: Any = getattr(sys, "monitoring", None)
    if monitoring is not None:
        tool = monitoring.COVERAGE_ID
        monitoring.use_tool_id(tool, "pokrycie_linii")

        def line(code: CodeType, number: int) -> object:
            # DISABLE wyłącza tylko to miejsce kodu, więc każda inna linia kosztuje jedno wywołanie na proces.
            return None if recorder.hit(code.co_filename, number) else monitoring.DISABLE

        monitoring.register_callback(tool, monitoring.events.LINE, line)
        monitoring.set_events(tool, monitoring.events.LINE)
        return

    def local(frame: FrameType, event: str, _: object) -> Any:
        if event == "line":
            recorder.hit(frame.f_code.co_filename, frame.f_lineno)
        return local

    def call(frame: FrameType, event: str, _: object) -> Any:
        return local if event == "call" and frame.f_code.co_filename in recorder.lines else None

    threading.settrace(call)
    sys.settrace(call)


_RECORDER: _Recorder | None = None


def pytest_configure(config: pytest.Config) -> None:
    global _RECORDER
    settings = json.loads(os.environ[VARIABLE])
    _RECORDER = _Recorder({path: set(lines) for path, lines in settings["linie"].items()})
    _start(_RECORDER)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> object:
    assert _RECORDER is not None
    _RECORDER.test = item.nodeid
    try:
        return (yield)
    finally:
        _RECORDER.test = None


def pytest_unconfigure(config: pytest.Config) -> None:
    if _RECORDER is None:
        return
    folder = Path(json.loads(os.environ[VARIABLE])["wynik"])
    hits = {test: {path: sorted(lines) for path, lines in files.items()} for test, files in _RECORDER.hits.items()}
    (folder / f"{os.getpid()}.json").write_text(json.dumps(hits), encoding="utf-8")
