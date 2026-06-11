"""Guard the cemaf-graph.html doc artifact against drift from src/cemaf."""

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "architecture"
HTML_PATH = DOCS_DIR / "cemaf-graph.html"
GENERATOR_PATH = DOCS_DIR / "build_graph_data.py"

DATA_RE = re.compile(r"/\*GRAPH-DATA\*/const DATA = (\{.*?\});/\*END-GRAPH-DATA\*/", re.DOTALL)

KNOWN = frozenset({"core", "agents", "memory", "tools", "cemaf"})


def load_generator() -> ModuleType:
    """Import build_graph_data.py from the docs directory."""
    spec = importlib.util.spec_from_file_location(name="build_graph_data", location=GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return load_generator()


@pytest.fixture(scope="module")
def embedded_data() -> dict[str, list[dict[str, str | int]]]:
    """Parse the JSON payload embedded between the HTML graph-data markers."""
    match = DATA_RE.search(HTML_PATH.read_text(encoding="utf-8"))
    assert match is not None, "graph-data markers missing from cemaf-graph.html"
    return json.loads(match.group(1))


def targets(generator: ModuleType, source: str, package: tuple[str, ...]) -> list[str]:
    """Run the generator's import extraction over a source snippet."""
    return generator.import_targets(tree=ast.parse(source), known=KNOWN, package=package)


class TestImportExtraction:
    """The extraction must capture every static import form, exactly once each."""

    def test_dotted_from_import(self, generator: ModuleType) -> None:
        src = "from cemaf.core.types import JSON\nfrom cemaf.agents.base import Agent\n"
        assert targets(generator, src, ("cemaf", "tools")) == ["core", "agents"]

    def test_root_from_import_multi_name(self, generator: ModuleType) -> None:
        src = "from cemaf import agents, core, __version__\n"
        assert targets(generator, src, ("cemaf",)) == ["agents", "core"]

    def test_plain_import_multi_alias(self, generator: ModuleType) -> None:
        src = "import cemaf.core, cemaf.memory, os\n"
        assert targets(generator, src, ("cemaf", "tools")) == ["core", "memory"]

    def test_bare_import_cemaf_is_facade_dependency(self, generator: ModuleType) -> None:
        assert targets(generator, "import cemaf\n", ("cemaf", "tools")) == ["cemaf"]

    def test_root_from_import_symbol_only_attributes_facade(self, generator: ModuleType) -> None:
        # `from cemaf import __version__, Result` runs the facade __init__
        src = "from cemaf import __version__, Result\n"
        assert targets(generator, src, ("cemaf", "cli")) == ["cemaf"]

    def test_root_from_import_mixed_modules_and_symbols(self, generator: ModuleType) -> None:
        # mixed: only the named modules are credited, facade is not double-counted
        src = "from cemaf import agents, __version__\n"
        assert targets(generator, src, ("cemaf", "tools")) == ["agents"]

    def test_unknown_submodule_skipped(self, generator: ModuleType) -> None:
        assert targets(generator, "import cemaf.nonexistent\n", ("cemaf", "tools")) == []

    def test_relative_import_resolves_across_packages(self, generator: ModuleType) -> None:
        src = "from ..core.types import JSON\nfrom .. import memory\n"
        assert targets(generator, src, ("cemaf", "tools")) == ["core", "memory"]

    def test_relative_import_within_own_package(self, generator: ModuleType) -> None:
        src = "from .base import Tool\n"
        # extraction reports the own package; collect() drops self-edges
        assert targets(generator, src, ("cemaf", "tools")) == ["tools"]

    def test_relative_import_beyond_root_ignored(self, generator: ModuleType) -> None:
        assert targets(generator, "from ...core import x\n", ("cemaf", "tools")) == []

    def test_docstring_lookalikes_not_counted(self, generator: ModuleType) -> None:
        src = '"""Example:\n    from cemaf.core import Result\n"""\nX = "from cemaf.memory import Y"\n'
        assert targets(generator, src, ("cemaf", "tools")) == []

    def test_non_cemaf_imports_ignored(self, generator: ModuleType) -> None:
        src = "import os\nfrom pathlib import Path\nfrom cemafx.core import z\n"
        assert targets(generator, src, ("cemaf", "tools")) == []

    def test_lazy_function_body_import_counted(self, generator: ModuleType) -> None:
        src = "def f():\n    from cemaf.memory.manager import MemoryManager\n    return 1\n"
        assert targets(generator, src, ("cemaf", "agents")) == ["memory"]


def test_embedded_nodes_match_source_modules(
    generator: ModuleType,
    embedded_data: dict[str, list[dict[str, str | int]]],
) -> None:
    expected = set(generator.discover_modules())
    embedded = {node["id"] for node in embedded_data["nodes"]}
    assert embedded == expected, (
        "cemaf-graph.html is stale — regenerate with: python docs/architecture/build_graph_data.py"
    )


def test_embedded_edges_reference_known_nodes(
    embedded_data: dict[str, list[dict[str, str | int]]],
) -> None:
    node_ids = {node["id"] for node in embedded_data["nodes"]}
    for edge in embedded_data["edges"]:
        assert edge["s"] in node_ids and edge["t"] in node_ids
        assert isinstance(edge["w"], int) and edge["w"] > 0


def test_embedded_edges_match_source_exactly(
    generator: ModuleType,
    embedded_data: dict[str, list[dict[str, str | int]]],
) -> None:
    """Edges including weights must match source; node LOC alone may drift."""
    fresh = json.loads(generator.collect().to_json())
    assert fresh["edges"] == embedded_data["edges"], (
        "cemaf-graph.html dependency edges are stale — regenerate with:"
        " python docs/architecture/build_graph_data.py"
    )
