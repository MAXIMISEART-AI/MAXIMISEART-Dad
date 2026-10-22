"""The features of ``verify-centrum-na-windowsie`` in Dad's order, and what each needs before it."""

from __future__ import annotations

FEATURES = ("instalacja", "komunikat-startu", "start-skrotem", "wskazanie-folderow", "aktualizacja")
# A feature driven alone first runs these, reported as preparation, not as verified features.
PREREQUISITES = {
    "instalacja": (),
    "komunikat-startu": ("instalacja",),
    "start-skrotem": ("instalacja",),
    "wskazanie-folderow": ("instalacja", "start-skrotem"),
    "aktualizacja": ("instalacja", "start-skrotem"),
}
