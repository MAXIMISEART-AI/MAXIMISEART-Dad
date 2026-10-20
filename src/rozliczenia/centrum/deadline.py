"""Pytanie o GitHuba w Diagnozie z łącznym limitem czasu, żeby bez sieci Diagnoza została krótka.

Limit gniazda nie obejmuje rozwiązywania nazwy, a skrzynka Zgłoszeń może pytać
kilka razy (strony otwartych Zgłoszeń), więc pytanie biegnie w osobnym wątku,
a Diagnoza czeka na nie najwyżej ``seconds``. Spóźniona odpowiedź przepada.
"""

from __future__ import annotations

from collections.abc import Callable
import threading
from typing import TypeVar

T = TypeVar("T")


def within(seconds: float, call: Callable[[], T], *, name: str) -> T | None:
    """Wynik ``call()``, gdy przyjdzie w ``seconds`` sekund; inaczej ``None``."""

    answer: list[T] = []
    worker = threading.Thread(target=lambda: answer.append(call()), name=name, daemon=True)
    worker.start()
    worker.join(seconds)
    return answer[0] if answer else None
