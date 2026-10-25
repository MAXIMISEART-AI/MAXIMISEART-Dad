"""Show that explore_outbox.py fails on broken variants of the Kolejka Skrzynki Zgłoszeń.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must end the checker's report with the
expected line. A mutation whose anchor text is no longer in ``outbox.py`` is reported as NIEAKTUALNA: update it to
the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

VERIFIED = Path("src/rozliczenia/centrum/outbox.py")
EXPLORER = ".agents/skills/verify-kolejka-skrzynki/scripts/explore_outbox.py"
NEW = "KOLEJKA: NOWE NARUSZENIE"

MUTATIONS = (
    Mutation(
        "nieudany komentarz pominięty zamiast końca wysyłki",
        (
            Edit(
                VERIFIED,
                "        if not isinstance(answer, Commented):\n            return answer\n",
                "        if not isinstance(answer, Commented):\n            continue\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "plik znika z kolejki, choć Skrzynka nie przyjęła części",
        NEW,
    ),
    Mutation(
        "do znalezionego issue okresu bez pierwszej części",
        (
            Edit(
                VERIFIED,
                "        number, comments = found, post.parts\n",
                "        number, comments = found, post.parts[1:]\n",
            ),
        ),
        (EXPLORER, "--scope", "watek-okresu"),
        "druga Kontrola ilości okresu traci część 1",
        NEW,
    ),
    Mutation(
        "issue okresu zakładane bez szukania",
        (
            Edit(
                VERIFIED,
                "    if found is None:\n        body, comments = post.opening()\n        opened = box.open_issue(thread.label",
                "    if True:\n        body, comments = post.opening()\n        opened = box.open_issue(thread.label",
            ),
        ),
        (EXPLORER, "--scope", "watek-okresu"),
        "jeden okres dostaje dwa issue Kontroli ilości",
        NEW,
    ),
    Mutation(
        "do znanego issue bez pierwszej części",
        (
            Edit(
                VERIFIED,
                "    return _comment_all(known.number, post.parts, box)\n",
                "    return _comment_all(known.number, post.parts[1:], box)\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "komentarz z odnośnikiem do Logów nie trafia do issue Uwagi taty",
        NEW,
    ),
    Mutation(
        "brak sieci pomija plik do następnego startu",
        (
            Edit(
                VERIFIED,
                '            return "brak-sieci", "stop"\n',
                '            return "brak-sieci", "next"\n',
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "po powrocie sieci wysyłka czeka do następnego startu Centrum",
        NEW,
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
