"""Regenerate the embedded graph data in cemaf-graph.html from src/cemaf source."""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "cemaf"
HTML = Path(__file__).resolve().parent / "cemaf-graph.html"

DATA_START = "/*GRAPH-DATA*/"
DATA_END = "/*END-GRAPH-DATA*/"

ROOT_PACKAGE = "cemaf"
EXCLUDED_DIRS = frozenset({"__pycache__"})
EXCLUDED_FILES = frozenset({"__init__.py"})

TIER_FOUNDATION = 0
TIER_FABRIC = 1
TIER_CAPABILITY = 2
TIER_ORCHESTRATION = 3
TIER_SELF_HOSTING = 4

TIERS: dict[str, int] = {
    "core": TIER_FOUNDATION,
    "config": TIER_FOUNDATION,
    "context": TIER_FABRIC,
    "events": TIER_FABRIC,
    "llm": TIER_FABRIC,
    "memory": TIER_FABRIC,
    "observability": TIER_FABRIC,
    "resilience": TIER_FABRIC,
    "retrieval": TIER_FABRIC,
    "bootstrap": TIER_ORCHESTRATION,
    "interceptors": TIER_ORCHESTRATION,
    "orchestration": TIER_ORCHESTRATION,
    "audit": TIER_SELF_HOSTING,
    "knowledge": TIER_SELF_HOSTING,
    "meta": TIER_SELF_HOSTING,
}

DESCRIPTIONS: dict[str, str] = {
    "agents": "Agent[Goal, Result] ABC, registry, built-in agents, auction selection",
    "audit": "EventBus subscriber → audit trail, quality trends, anomaly detection",
    "blueprint": "Semantic blueprints for structured generation + harvest flywheel",
    "bootstrap": "create_executor() composition root — wires RuntimeServices",
    "cache": "Result caching with TTL",
    "catalog": "Discover external models and artifacts through typed adapters",
    "citation": "Source citation tracking",
    "cli": "Command-line interface",
    "config": "Settings, env loading, provider registry",
    "context": "Immutable Context, compiler, token budgets, provenance patches",
    "core": "Domain types, enums, Result[T], utc_now(), generate_id()",
    "council": "Deliberative multi-agent decisions — vote aggregation, ballots",
    "docs_api": "Expose CEMAF's own docs and docstrings to LLMs",
    "evals": "Deterministic / semantic / LLM-judge evaluation, online pipeline",
    "events": "EventBus pub/sub with typed EventType enum",
    "generation": "Content generation strategies",
    "improvement": "Self-learning feedback loop",
    "ingestion": "Data ingestion pipelines",
    "interceptors": "PRE→execute→POST chain on every AGENT node; quality gates",
    "iteration": "Failure-feedback loop — parse failures, bounded re-attempts",
    "knowledge": "Knowledge graph backed by MemoryManager; hub-and-spoke cache",
    "llm": "LLMClient protocol, provider adapters, resilient wrapper, router",
    "mcp": "Model Context Protocol bridges and adapter",
    "memory": "Semantic + episodic memory, tiers, dedup, extraction, sessions",
    "meta": "Self-hosting agents, tools, DAGs — CEMAF introspecting itself",
    "moderation": "Content safety pipeline",
    "observability": "Structured logging, Prometheus metrics, health, tracing",
    "orchestration": "DAGExecutor, node executors, RuntimeServices, resolvers",
    "persistence": "Run and entity persistence",
    "replay": "Execution replay and debugging",
    "resilience": "Retry, circuit breaker, rate limiter",
    "retrieval": "VectorStore and EmbeddingProvider protocols",
    "rlm": "Recursive Language Model — divide-and-conquer context queries",
    "sandbox": "Confined, bounded, env-scrubbed subprocess execution",
    "scheduler": "Task scheduling — triggers, gates, async job executor",
    "security": "Data masking, RBAC/ABAC, audit signing",
    "skills": "Skill protocol + built-in kits (file/shell/test coding kit)",
    "state": "Typed, persisted, observable state machines",
    "streaming": "Streaming response handling",
    "tools": "Tool ABC, ToolSchema, registry, @tool decorator",
    "trust": "Reliability tracking for dynamically generated tools and skills",
    "validation": "Input/output validation",
}


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One module node as the HTML's JS consumes it."""

    id: str
    loc: int
    fan_in: int
    fan_out: int
    tier: int
    description: str

    def to_payload(self) -> dict[str, str | int]:
        """Compact key form matching the JS contract in cemaf-graph.html."""
        return {
            "id": self.id,
            "loc": self.loc,
            "fi": self.fan_in,
            "fo": self.fan_out,
            "tier": self.tier,
            "d": self.description,
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One aggregated source→target import edge with its statement count."""

    source: str
    target: str
    weight: int

    def to_payload(self) -> dict[str, str | int]:
        """Compact key form matching the JS contract in cemaf-graph.html."""
        return {"s": self.source, "t": self.target, "w": self.weight}


@dataclass(frozen=True, slots=True)
class GraphData:
    """Full graph payload plus the total import-statement count."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    import_count: int

    def to_json(self) -> str:
        """Serialize to the compact JSON form the HTML embeds."""
        payload = {
            "nodes": [node.to_payload() for node in self.nodes],
            "edges": [edge.to_payload() for edge in self.edges],
        }
        return json.dumps(obj=payload, separators=(",", ":"))


def discover_modules() -> dict[str, tuple[Path, ...]]:
    """Map each top-level module name to its Python source files."""
    modules: dict[str, tuple[Path, ...]] = {}
    for entry in sorted(SRC.iterdir()):
        if entry.is_dir() and entry.name not in EXCLUDED_DIRS:
            modules[entry.name] = tuple(sorted(entry.rglob("*.py")))
        elif entry.suffix == ".py" and entry.name not in EXCLUDED_FILES:
            modules[entry.stem] = (entry,)
    return modules


def import_targets(tree: ast.AST, known: frozenset[str]) -> list[str]:
    """Extract top-level cemaf module names this AST imports."""
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            parts = node.module.split(".")
            if parts[0] != ROOT_PACKAGE:
                continue
            if len(parts) > 1:
                if parts[1] in known:
                    targets.append(parts[1])
            else:
                targets.extend(alias.name for alias in node.names if alias.name in known)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == ROOT_PACKAGE and len(parts) > 1 and parts[1] in known:
                    targets.append(parts[1])
    return targets


def collect() -> GraphData:
    """Scan src/cemaf and build the module dependency graph via AST parsing."""
    modules = discover_modules()
    known = frozenset(modules)
    loc: dict[str, int] = {}
    edge_weights: dict[tuple[str, str], int] = {}
    for module, files in modules.items():
        total = 0
        for source_file in files:
            text = source_file.read_text(encoding="utf-8")
            total += len(text.splitlines())
            tree = ast.parse(source=text, filename=str(source_file))
            for target in import_targets(tree=tree, known=known):
                if target != module:
                    edge_weights[(module, target)] = edge_weights.get((module, target), 0) + 1
        loc[module] = total

    fan_in: dict[str, int] = dict.fromkeys(modules, 0)
    fan_out: dict[str, int] = dict.fromkeys(modules, 0)
    for source, target in edge_weights:
        fan_out[source] += 1
        fan_in[target] += 1

    for module in sorted(set(modules) - set(DESCRIPTIONS)):
        print(
            f"warning: new module '{module}' has no DESCRIPTIONS entry"
            " (and defaults to the Capabilities tier unless added to TIERS)",
            file=sys.stderr,
        )

    nodes = tuple(
        GraphNode(
            id=module,
            loc=loc[module],
            fan_in=fan_in[module],
            fan_out=fan_out[module],
            tier=TIERS.get(module, TIER_CAPABILITY),
            description=DESCRIPTIONS.get(module, ""),
        )
        for module in sorted(modules)
    )
    edges = tuple(
        GraphEdge(source=source, target=target, weight=weight)
        for (source, target), weight in sorted(edge_weights.items())
    )
    return GraphData(nodes=nodes, edges=edges, import_count=sum(edge_weights.values()))


def splice(html: str, payload: str) -> str:
    """Replace the marker-delimited data block in the HTML with a fresh payload."""
    if DATA_START not in html or DATA_END not in html:
        raise SystemExit(f"markers {DATA_START}…{DATA_END} not found in {HTML}")
    start = html.index(DATA_START)
    end = html.index(DATA_END, start) + len(DATA_END)
    return html[:start] + payload + html[end:]


def main() -> None:
    """Splice freshly collected graph data between the HTML data markers."""
    data = collect()
    payload = f"{DATA_START}const DATA = {data.to_json()};{DATA_END}"
    HTML.write_text(splice(html=HTML.read_text(encoding="utf-8"), payload=payload), encoding="utf-8")
    print(
        f"wrote {len(data.nodes)} nodes, {len(data.edges)} edges, {data.import_count} imports → {HTML.name}"
    )


if __name__ == "__main__":
    main()
