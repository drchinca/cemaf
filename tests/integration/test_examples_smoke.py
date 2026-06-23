"""Every self-contained example must actually run — not just import.

Two examples (extensibility_patterns, generate_etl_blueprint) silently rotted
when the BlueprintBuilder/entity API moved underneath them; nothing in CI ran
the examples, so import-only checks missed it. This smoke test executes each
no-external-dependency example as a subprocess and asserts a clean exit, so a
shipped example can never again be broken on main.

Examples needing live services (ollama_*) are excluded by name.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

# Examples that require a live external service / network and cannot run in CI.
_NEEDS_EXTERNAL = frozenset({"ollama_gemma.py", "ollama_gemma_tiered.py"})


def _self_contained_examples() -> list[str]:
    return sorted(
        path.name
        for path in _EXAMPLES_DIR.glob("*.py")
        if path.name != "__init__.py" and path.name not in _NEEDS_EXTERNAL
    )


@pytest.mark.parametrize("example_name", _self_contained_examples())
def test_example_runs_clean(example_name: str) -> None:
    """Each self-contained example exits 0 when run as a script."""
    result = subprocess.run(
        [sys.executable, str(_EXAMPLES_DIR / example_name)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"examples/{example_name} failed (exit {result.returncode}).\n"
        f"--- stdout tail ---\n{result.stdout[-1500:]}\n"
        f"--- stderr tail ---\n{result.stderr[-1500:]}"
    )


def test_smoke_covers_expected_example_count() -> None:
    """Guard: if someone adds an example, this list grows — keeps coverage honest."""
    found = _self_contained_examples()
    assert len(found) >= 7, f"expected >=7 self-contained examples, found {found}"
