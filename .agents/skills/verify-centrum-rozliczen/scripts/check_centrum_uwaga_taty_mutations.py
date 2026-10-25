"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `uwaga-taty` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/mutacje.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import DAD_NOTES, UWAGA
from mutacje import Edit, Mutation, check_all

MUTATIONS = (
    Mutation(
        "komentarz z odnośnikiem do odrzuconych Logów nie powstaje",
        (
            Edit(
                DAD_NOTES,
                "        outbox.post(Post(target, period=None, run_id=run_id, header=None, parts=(_logs_gone(run_id),)))\n",
                "        pass\n",
            ),
        ),
        UWAGA,
        "Maks nie dostaje odnośnika do Logów, które dotarły po Uwadze",
    ),
    Mutation(
        "komentarz po odrzuconych Logach bez odnośnika",
        (
            Edit(
                DAD_NOTES,
                "            return replace(post, parts=(_logs_arrived(post.run_id, address),))\n",
                "            return post\n",
            ),
        ),
        UWAGA,
        "Maks dostaje komentarz, że Logi nie dotrą, choć dotarły",
    ),
    Mutation(
        "„nie dotarły” zamienione na „w drodze”",
        (Edit(DAD_NOTES, "        return _rejected_logs_line(run_id)\n", "        return _logs_line(run_id, None)\n"),),
        UWAGA,
        "wysłana Uwaga mówi, że Logi są w drodze, choć Skrzynka je odrzuciła",
    ),
    Mutation(
        "„nie powstały” zamienione na „nie dotarły”",
        (Edit(DAD_NOTES, "    if rejected(run_id):\n", "    if True:\n"),),
        UWAGA,
        "Uwaga obiecuje odnośnik do Logów, których nie ma w kolejce",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
