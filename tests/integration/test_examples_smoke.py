"""Every example runs — examples/ can't silently rot.

Auto-discovers examples/**/*.py, imports each, and runs its async `main()`. An
example that depends on something not always present (a live Ollama daemon) or
has a dedicated guard (release_engine) defines `smoke_skip_reason() -> str | None`:
it returns None when the example can run here, or a human reason when it can't —
so the ollama examples actually run when Ollama IS up, and skip with a clear
message when it isn't.

This is the contract that makes examples trustworthy: if it's in examples/, it
works by running `uv run python examples/<it>.py`.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

import pytest

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _discover() -> list[Path]:
    return sorted(p for p in _EXAMPLES_DIR.rglob("*.py") if p.name != "__init__.py")


def _load(path: Path) -> ModuleType:
    name = f"example_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so module-level @dataclass can resolve its own module.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("example_path", _discover(), ids=lambda p: str(p.relative_to(_EXAMPLES_DIR)))
async def test_example_runs_offline(example_path: Path) -> None:
    module = _load(example_path)

    skip_check = getattr(module, "smoke_skip_reason", None)
    if callable(skip_check):
        reason = skip_check()
        if reason is not None:
            pytest.skip(reason)

    main = getattr(module, "main", None)
    assert callable(main), f"{example_path.name} must define a main()"
    assert inspect.iscoroutinefunction(main), f"{example_path.name} main() must be async"

    # The example's own in-main() assertions are the behavioral contract; a clean
    # run (no exception) is the smoke contract.
    await main()
