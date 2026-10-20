"""One module per verified Centrum feature (``features/<feature>.md``), driven by ``drive_centrum.py``.

The constants here are shared with ``run_centrum_verification.py``, which imports them before it checks that
Playwright is installed, so this module imports nothing.
"""

# Run only when named, never in `all`: the measurement takes minutes, needs a quiet CPU, and its own fixture variant.
EXPLICIT_FEATURES = ("wydajnosc",)
# wydajnosc: repetitions of every scenario per CPU profile unless `--powtorzenia` says otherwise; a baseline
# comes only from a run with this many (features/wydajnosc.md).
DEFAULT_REPEATS = 5
