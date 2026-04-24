---
name: dad-excel-update
description: Append Excel rows via openpyxl z OneDrive lock detection + UTF-8 polskie znaki + SHA-256 checksum. Use dla Step 3.
---

# dad-excel-update

**Status:** Phase 0 stub. Phase 2 target: 4h effort.

## Purpose

Step 3 — zapisuje wyekstraktowane dane (pracownik, kod, ilość, lokacja) do pliku Excel taty. Bezpieczeństwo: nie nadpisuj wierszy, nie psuj pliku, wykryj concurrent edit tata.

## Inputs

- `cfg.excel_path: Path` — plik Excel taty
- `routed_emails: dict` — output Step 2
- `code_mapping: dict` — z config/
- `excel_schema: dict` — z config/

## Outputs

- Appended rows w Excel
- Snapshot w `runtime/state/excel-snapshots/YYYY-MM-DD-HHMMSS.xlsx`
- Return: `list[dict]` of added rows (dla Step 4 verification)

## Algorithm

1. Pre-flight: `lib.excel_safe_writer.is_excel_locked(excel_path)` — jeśli tak retry
2. Snapshot: `lib.excel_safe_writer.snapshot(excel_path, snapshots_dir)`
3. Checksum before: `sha256_file(excel_path)`
4. Load workbook z `openpyxl.load_workbook(keep_vba=False, data_only=False)`
5. Per routed email:
   - Extract data (code via Haiku classifier → match config/code_mapping.yaml)
   - Append row do primary_sheet per schema rules
   - Set status='ANSWER' (Step 4 może downgrade)
6. Save workbook
7. Checksum after: verify nie było concurrent edit
8. If mismatch → rollback snapshot + alert

## Anti-patterns

- ❌ Write gdy lock present — Rule anti-pattern
- ❌ Usuwać wiersze — Rule #1 Floor Never Drops
- ❌ openpyxl `data_only=True` — stracimy formuły taty
- ❌ Hardcode kolumn — zawsze z `config/excel_schema.yaml`
- ❌ UTF-8 BOM w kodach kolumn (openpyxl native UTF-8 OK — NIE dodawaj BOM)

## Reuse

- `scripts/lib/excel_safe_writer.py` — lock detection + snapshot primitives
- openpyxl 3.1.5 dokumentacja (wspiera polskie znaki natively)
