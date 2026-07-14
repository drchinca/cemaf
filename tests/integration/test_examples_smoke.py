"""Every example has an offline smoke path — examples/ can't silently rot.

Auto-discovers examples/**/*.py, imports each, and runs its async `smoke_main()`
when present, otherwise its async `main()`. Examples that normally need a local
service use `smoke_main()` to exercise the same CEMAF wiring with deterministic
in-process adapters.

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

    main = getattr(module, "smoke_main", None) or getattr(module, "main", None)
    assert callable(main), f"{example_path.name} must define main() or smoke_main()"

    # Some examples parse argv via argparse; under pytest sys.argv is the pytest
    # command line, so present a clean argv (program name only) while running them.
    saved_argv = sys.argv
    sys.argv = [str(example_path)]
    try:
        # The example's own in-main() assertions are the behavioral contract; a
        # clean run (no exception, exit-0 if it returns a code) is the smoke
        # contract. Examples may be async when they exercise async CEMAF paths.
        if inspect.iscoroutinefunction(main):
            result = await main()
        else:
            result = main()
    finally:
        sys.argv = saved_argv

    if isinstance(result, int):
        assert result == 0, f"{example_path.name} main() returned non-zero exit {result}"
