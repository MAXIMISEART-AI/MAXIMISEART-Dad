"""Wynik referencyjny scenariusza zamrożony z commita i bramka poprawności pomiaru względem niego.

Kody Komunikatów nie wychodzą poza proces (nie pokazuje ich ani terminal, ani rekord
metryk), więc Komunikaty są porównywane jako linie terminala (Komunikaty,
podsumowanie i postęp, z czasami zastąpionymi przez ``<N> ms``): treść Komunikatu
wyznacza jego kod, więc ta sama linia to ten sam kod, a porównanie linii jest
nawet ostrzejsze niż porównanie kodów.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from benchmark import BenchmarkError
from benchmark.lustro import worker_settlements_folder
from benchmark.uruchomienie import Przebieg, git_output, remove_worker_settlements, run_przebieg
from porownanie_rozliczen import CATEGORIES, compare_worker_settlements


ORACLE_CATEGORIES = (*CATEGORIES, "liczniki", "komunikaty")


REFERENCE_RESULT = "wynik.json"


def reference_folder(references: Path, mirror: Path, worker_template: Path) -> Path:
    """Wyniki referencyjne lustra zamrożone z tym Wzorcem rozliczenia pracownika.

    Lustro nie zależy od Wzorca rozliczenia pracownika (używa go dopiero Przebieg
    rozliczeń), więc klucz wyniku referencyjnego to lustro i odcisk tego Wzorca:
    wynik zamrożony z jednym Wzorcem nigdy nie jest porównywany z pomiarem na innym.
    """

    fingerprint = hashlib.sha256(worker_template.read_bytes()).hexdigest()[:12]
    return references / f"{mirror.name}-wzorzec-{fingerprint}"


def freeze_reference(
    references: Path, mirror: Path, commit: str, config: Path, worker_template: Path
) -> Path:
    """Wynik referencyjny lustra z commita ``commit``: jego Przebieg rozliczeń w tymczasowym worktree gita."""

    resolved = git_output("rev-parse", "--verify", f"{commit}^{{commit}}")
    if resolved is None:
        raise BenchmarkError(f"Nie ma commita {commit}.")
    sha = resolved.strip()
    target = reference_folder(references, mirror, worker_template) / sha
    if target.exists():
        raise BenchmarkError(f"Wynik referencyjny {sha[:7]} dla {target.parent.name} już jest: {target}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="benchmark-referencja-") as scratch_name:
        scratch = Path(scratch_name)
        checkout = scratch / "checkout"
        if git_output("worktree", "add", "--detach", str(checkout), sha) is None:
            raise BenchmarkError(f"Nie udało się zbudować commita {sha[:7]} w tymczasowym worktree gita.")
        try:
            przebieg = run_przebieg(checkout, mirror, config, worker_template, scratch)
        finally:
            git_output("worktree", "remove", "--force", str(checkout))
        staging = Path(tempfile.mkdtemp(prefix=f".{sha}.staging-", dir=target.parent))
        try:
            worker_settlements = worker_settlements_folder(mirror)
            shutil.copytree(worker_settlements, staging / worker_settlements.name)
            result = {"git_sha": sha, "counters": przebieg.metrics["counters"], "terminal": przebieg.terminal}
            (staging / REFERENCE_RESULT).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            staging.rename(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            remove_worker_settlements(worker_settlements_folder(mirror))
    return target


def find_reference(references: Path, mirror: Path, worker_template: Path, commit: str | None) -> Path | None:
    """Wynik referencyjny lustra i Wzorca rozliczenia pracownika: wskazany prefiksem commita albo jedyny, jaki jest."""

    folder = reference_folder(references, mirror, worker_template)
    frozen = sorted(
        path for path in folder.glob("*") if not path.name.startswith(".") and (path / REFERENCE_RESULT).is_file()
    )
    if commit is not None:
        matching = [path for path in frozen if path.name.startswith(commit)]
        if len(matching) != 1:
            raise BenchmarkError(
                f"Dla {mirror.name} nie ma wyniku referencyjnego z commita {commit} zamrożonego z tym Wzorcem "
                f"rozliczenia pracownika ({folder.name}); zamroź go przez freeze z tymi samymi Wzorcami."
            )
        return matching[0]
    if len(frozen) > 1:
        raise BenchmarkError(f"Dla {folder.name} jest kilka wyników referencyjnych; wskaż jeden przez --reference.")
    return frozen[0] if frozen else None


def _line_differences(reference: Sequence[str], candidate: Sequence[str]) -> int:
    matcher = difflib.SequenceMatcher(a=reference, b=candidate, autojunk=False)
    return sum(
        max(end_a - start_a, end_b - start_b)
        for tag, start_a, end_a, start_b, end_b in matcher.get_opcodes()
        if tag != "equal"
    )


def check_oracle(reference: Path, mirror: Path, przebieg: Przebieg) -> dict[str, Any]:
    """Bramka poprawności: liczba różnic w każdej kategorii względem wyniku referencyjnego, bez treści."""

    frozen = json.loads((reference / REFERENCE_RESULT).read_text(encoding="utf-8"))
    worker_settlements = worker_settlements_folder(mirror)
    differences = compare_worker_settlements(reference / worker_settlements.name, worker_settlements)
    counters, frozen_counters = przebieg.metrics["counters"], frozen["counters"]
    differences["liczniki"] = sum(
        counters.get(name) != frozen_counters.get(name) for name in {*counters, *frozen_counters}
    )
    differences["komunikaty"] = _line_differences(frozen["terminal"], przebieg.terminal)
    return {
        "wynik": "niezgodny" if any(differences.values()) else "zgodny",
        "referencja": reference.name,
        "roznice": {category: differences[category] for category in ORACLE_CATEGORIES},
    }
