"""Guard the cemaf-graph.html doc artifact against drift from src/cemaf."""

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


def load_generator() -> ModuleType:
    """Import build_graph_data.py from the docs directory."""
    spec = importlib.util.spec_from_file_location(name="build_graph_data", location=GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def embedded_data() -> dict[str, list[dict[str, str | int]]]:
    """Parse the JSON payload embedded between the HTML graph-data markers."""
    match = DATA_RE.search(HTML_PATH.read_text(encoding="utf-8"))
    assert match is not None, "graph-data markers missing from cemaf-graph.html"
    return json.loads(match.group(1))


def test_embedded_nodes_match_source_modules(
    embedded_data: dict[str, list[dict[str, str | int]]],
) -> None:
    generator = load_generator()
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


def test_embedded_dependency_pairs_match_source(
    embedded_data: dict[str, list[dict[str, str | int]]],
) -> None:
    """Edge pairs must match source; weights may drift without forcing a regen."""
    generator = load_generator()
    fresh = json.loads(generator.collect().to_json())
    fresh_pairs = {(edge["s"], edge["t"]) for edge in fresh["edges"]}
    embedded_pairs = {(edge["s"], edge["t"]) for edge in embedded_data["edges"]}
    assert fresh_pairs == embedded_pairs, (
        "cemaf-graph.html dependency edges are stale — regenerate with:"
        " python docs/architecture/build_graph_data.py"
    )
