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

from cele_mutacji_centrum import BUILD, DAD_NOTES, UWAGA
from mutacje import Edit, Mutation, check_all

FIELDS = Edit(BUILD, "`-m-1 flex flex-col gap-5 overflow-y-auto p-1`", "`-m-1 flex min-h-0 flex-col gap-5 p-1`")
DOTYCZY = Edit(
    BUILD, "`has-data-[slot=radio-group]:min-h-32 has-[>p+[data-slot=radio-group]]:min-h-38`", "`min-h-0`"
)
PREVIEW = "`flex min-h-16 flex-col gap-1 overflow-y-auto rounded-lg bg-muted/50 p-3 text-sm`"

MUTATIONS = (
    Mutation(
        "pola okna Uwagi się nie przewijają",
        (FIELDS,),
        UWAGA,
        "przy niskim oknie przełącznik „Dotyczy” i „Maks dostanie” leżą pod stopką i nie da się do nich przewinąć (#488)",
    ),
    Mutation(
        "okno Uwagi jak na main",
        (FIELDS, DOTYCZY, Edit(BUILD, PREVIEW, PREVIEW.replace("min-h-16", "min-h-0"))),
        UWAGA,
        "przy niskim oknie „Dotyczy” kurczy się pod przełącznik, a pola się nie przewijają (#488)",
    ),
    Mutation(
        "„Dotyczy” kurczy się pod przełącznik",
        (DOTYCZY,),
        UWAGA,
        "przy niskim oknie lista Uruchomień albo przełącznik nachodzi na „Maks dostanie” (#488)",
    ),
    Mutation(
        "„Maks dostanie” nie oddaje wysokości",
        (Edit(BUILD, PREVIEW, PREVIEW.replace("min-h-16", "shrink-0")),),
        UWAGA,
        "przy pełnym oknie lista Uruchomień jest niższa niż na main, bo wysokość oddaje tylko ona (#498)",
    ),
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
