"""Zwiad #401: liczy powtórzenia i drukuje te, w których pomocnik dalej dopisywał."""

import json
import pathlib
import sys

records = [json.loads(line) for path in pathlib.Path(sys.argv[1]).glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]
bad = [r for r in records if r["beating"] or not r["result_ok"]]
print(f"POWTÓRZENIA {len(records)} | ŻYWY POMOCNIK {len(bad)}")
no_helper = [r for r in records if not r["helper_pid"]]
print(f"bez pomocnika przed limitem: {len(no_helper)}")
print("taskkill rc:", sorted({str(r['taskkill'] if r['taskkill'] == 'timeout' else r['taskkill'][0]) for r in records}))
print("taskkill dł. max:", max(r["t_taskkill_end"] - r["t_timeout"] for r in records))
for r in bad:
    print(json.dumps(r, indent=1, ensure_ascii=False))
