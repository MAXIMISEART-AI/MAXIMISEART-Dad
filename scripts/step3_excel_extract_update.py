"""Step 3 — Excel extract + update (openpyxl, OneDrive lock-aware).

Phase 0 stub. Phase 2 implementation:
- Pre-flight: check lock (lib.excel_safe_writer.is_excel_locked) → retry policy
- Snapshot Excel PRZED write (lib.excel_safe_writer.snapshot)
- Load workbook → primary_sheet → find append row per schema.excel_structure_type
- For each routed email:
  - Extract: date, employee_name, code (Haiku classify), quantity, location, notes
  - Set status='ANSWER' (Step 4 may downgrade)
  - Append row z source email-id dla audytu
- Post-write checksum verification
- Rollback snapshot jeśli checksum mismatch (concurrent edit przez tatę)

Reuse: scripts/lib/excel_safe_writer.py (lock + snapshot primitives)
"""
from __future__ import annotations


def append_rows(excel_path, routed_emails: dict, code_mapping: dict, schema: dict) -> list[dict]:
    """Append rows to Excel. Returns list of added row dicts (for Step 4 verification)."""
    raise NotImplementedError("Phase 2: implement openpyxl append + lock handling")
