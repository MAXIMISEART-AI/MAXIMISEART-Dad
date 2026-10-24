"""Sonda #401: ile razy pomocnik Gita jeszcze żył, gdy update() wróciło."""

import collections
import json
import pathlib
import sys

records = [json.loads(line) for path in pathlib.Path(sys.argv[1]).glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]
states = collections.Counter((r["at_return"] or "brak-pomocnika").split(",")[0] for r in records)
alive = sum(1 for r in records if (r["at_return"] or "").startswith("wait=0x102"))
wrong = sum(1 for r in records if not r["result_ok"])
print(f"SONDA | powtórzenia={len(records)} | żywy przy powrocie={alive} | zły wynik={wrong} | stany={dict(states)}")
