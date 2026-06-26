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
ROOT_INIT = "__init__.py"
EXCLUDED_DIRS = frozenset({"__pycache__"})

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
    "cemaf": TIER_ORCHESTRATION,
    "collision": TIER_ORCHESTRATION,
    "interceptors": TIER_ORCHESTRATION,
    "orchestration": TIER_ORCHESTRATION,
    "audit": TIER_SELF_HOSTING,
    "knowledge": TIER_SELF_HOSTING,
    "meta": TIER_SELF_HOSTING,
}

HOW: dict[str, str] = {
    "agents": (
        "Define an Agent[GoalT, ResultT] subclass; register it in an "
        "AgentRegistry; reference its AgentID from a DAG node. The executor "
        "resolves the agent and calls run(goal, context). For dynamic pick "
        "between candidates of the same role, opt-in to the auction selector "
        "via RuntimeServices.agent_selector."
    ),
    "audit": (
        "create_audit_subscriber(event_bus) — every TASK_COMPLETED / "
        "QUALITY_ALERT / EVAL_COMPLETED becomes an AuditEntry. Query the "
        "AuditTrail for quality trends and z-score anomaly detection. "
        "Pull-based: nothing emits these unless something subscribes."
    ),
    "blueprint": (
        "Author a SemanticBlueprint (parser + library), or harvest one from "
        "high-scoring runs via create_blueprint_harvester(event_bus, library). "
        "The runtime can then pull `library.search(...)` to instantiate a DAG "
        "from a saved blueprint instead of hand-wiring it."
    ),
    "bootstrap": (
        "Top-level entry point: create_executor(agent_registry=, services=) "
        "→ DAGExecutor. This is the composition root — it wires "
        "ContextNodeExecutor, the resolver chain, and RuntimeServices. "
        "Most apps call this once at startup."
    ),
    "cache": (
        "ResultCache with TTL. Wrap an expensive computation (LLM call, "
        "retrieval) in cache.get_or_set(key, compute_fn). Backed by an "
        "in-memory store by default; swap via the protocol for Redis."
    ),
    "catalog": (
        "Adapters expose external model/artifact registries (HuggingFace, "
        "vendor catalogs) through one CatalogProvider protocol. Use to "
        "discover models the framework can route to without hard-coding."
    ),
    "collision": (
        "Coordinate concurrent agents that intend to write overlapping context "
        "paths. create_collision_coordinator(); each agent register(write_set) then "
        "advise_against_cohort(agent_id) → an Advisory. At resolution level the "
        "lower-priority agent steers (defers) while the higher holds — deterministic, "
        "TCAS-style. Pure-math risk in collision.risk; no execution-security concern."
    ),
    "cemaf": (
        "Read this node's outgoing edges to see which submodules the "
        "public surface re-exports — tracks what's *officially* part of "
        "the framework API. Direct `from cemaf.x` imports go to x; symbol "
        "imports like `from cemaf import Result` go through this node."
    ),
    "citation": (
        "CitationTracker records (claim, source) pairs as agents generate "
        "content. Combine with the eval harness to prove every produced "
        "claim cites a retrieved fact (membership constraint)."
    ),
    "cli": (
        "Command-line entry into CEMAF — `python -m cemaf …`. Wires the "
        "facade against argparse; shells out to bootstrap.create_executor()."
    ),
    "config": (
        "Settings(BaseModel) loaded from CEMAF_* env vars. Provider "
        "registry maps name → factory. Read once at startup; pass concrete "
        "values down — never reach back here from runtime code."
    ),
    "context": (
        "Build an immutable Context, register ContextSources, then call "
        "ContextCompiler.compile(query, budget=TokenBudget(...)). Priority-"
        "based selection drops low-priority sources first when over budget. "
        "Mutations land via ContextPatch with provenance."
    ),
    "core": (
        "Don't subclass these — import them. Result.ok(...)/Result.fail(...) "
        "for fallible returns; utc_now() for any timestamp; generate_id() "
        "for any ID; NewType wrappers (AgentID, ToolID) for type-safe IDs."
    ),
    "council": (
        "Compose a Council from N member agents and a VoteAggregator "
        "(majority / weighted / quorum / unanimous). The council's result "
        "becomes a NodeResult.output that steers the DAG; ballots are "
        "preserved for audit."
    ),
    "docs_api": (
        "Mounts CEMAF's own docs + docstrings as a tool surface so meta-"
        "agents can ask 'how do I use module X' without an external index."
    ),
    "evals": (
        "Three tiers: deterministic regex/equality, semantic embedding "
        "similarity, LLM judge. Wire as an OnlineEvalPipeline subscribed "
        "to TASK_COMPLETED, or as a GateEvalInterceptor that blocks "
        "downstream nodes when scores fall below threshold."
    ),
    "events": (
        "EventBus.publish(EventType.X, payload) and bus.subscribe(EventType.X, "
        "handler). Strongly-typed EventType enum is the contract; payloads "
        "are JSON dicts. Handler exceptions are logged, never raised."
    ),
    "generation": (
        "Pluggable strategies for token-by-token / structured / template-"
        "filled output. Used by writer-style agents that need more than "
        "a single LLMClient.complete() call."
    ),
    "improvement": (
        "Self-learning hook — feed outcome signals back, rank tool/agent "
        "reliability via the trust module. Opt-in; disabled by default."
    ),
    "ingestion": (
        "Pipeline primitives for transforming raw documents → "
        "ContextSources / MemoryItems. Compose readers, chunkers, "
        "embedders before handing off to memory or retrieval."
    ),
    "interceptors": (
        "Build a small InterceptorPipeline of PRE/POST handlers; "
        "RuntimeServices.interceptor_pipeline runs it around every AGENT "
        "node. GateEvalInterceptor in POST aborts downstream when the "
        "agent's output fails an eval."
    ),
    "iteration": (
        "Wrap a coding-style agent in IterationLoop(parser, sandbox, "
        "max_attempts=N). Pytest/ruff/mypy parsers turn output into "
        "FailureSignals; the loop re-runs the agent with the failure "
        "context appended until tests pass or budget is exhausted."
    ),
    "knowledge": (
        "MemoryBackedKnowledgeGraph stores entities as MemoryItems and "
        "relations as per-entity indexes. Wrap in HubKnowledgeGraph for a "
        "bounded-LRU hub-and-spoke cache when point reads are hot."
    ),
    "llm": (
        "Implement LLMClient or use anthropic/openai_compat/ollama "
        "adapters. Wrap in create_resilient_client(...) for retry + "
        "circuit breaker + rate limit. ModelRouter picks a tier by "
        "complexity score so cheap calls stay cheap."
    ),
    "mcp": (
        "Expose tools/resources to LLMs via Model Context Protocol. "
        "Bridges convert CEMAF Tool objects into MCP tool definitions; "
        "the adapter handles the JSON-RPC framing."
    ),
    "memory": (
        "create_memory_manager(memory_store=, embedding_provider=). "
        "manager.remember(item, scope=) persists; manager.recall(query) "
        "retrieves with three-tier progressive search. Sessions add "
        "lifecycle (bootstrap → ingest → compact → dispose)."
    ),
    "meta": (
        "create_meta_executor() registers MetaArchitect / MetaSynthesizer / "
        "MetaAuditor / MetaKnowledgeGraph and three pre-built DAGs "
        "(self_audit, feature_synthesis, knowledge_refresh). CEMAF "
        "introspecting itself — opt-in, never imported by base code."
    ),
    "moderation": (
        "ModerationPipeline of stacked safety checks. Intercept inputs "
        "before LLM calls and outputs before user delivery."
    ),
    "observability": (
        "create_structured_logger() emits JSON lines with correlation IDs. "
        "PrometheusMetrics exposes /metrics. configure_otel() wires OTel "
        "GenAI spans/metrics in one call. Wire via RuntimeServices."
    ),
    "orchestration": (
        "DAGExecutor.run(dag) topo-sorts nodes and dispatches via the "
        "resolver chain (council → auction → static, first match wins). "
        "Each node executes inside a ContextNodeExecutor that builds the "
        "agent's goal from input_mapping. Add a node 'kind' = register a "
        "resolver, not an if-branch."
    ),
    "persistence": (
        "Run/entity persistence — durable state for resumable executions "
        "and replay. Pluggable backend; in-memory default for tests."
    ),
    "replay": (
        "Record an execution; replay it deterministically against the "
        "same registry to debug why a node took the path it did. "
        "Different from persistence: replay rewinds the *event stream*."
    ),
    "resilience": (
        "RetryPolicy + CircuitBreaker + RateLimiter combinator. "
        "create_resilient_client() composes all three around an LLMClient; "
        "use the same primitives around any flaky external call."
    ),
    "retrieval": (
        "Implement VectorStore + EmbeddingProvider, or use an adapter. "
        "Memory uses these for semantic recall; the eval harness uses "
        "them for citation-membership checks."
    ),
    "rlm": (
        "RecursiveLanguageModel — split a too-large query into a tree, "
        "answer leaves, fold up. Use when context exceeds the model "
        "window and you can't pre-compact (e.g., novel codebase QA)."
    ),
    "sandbox": (
        "ShellSandbox(workdir=, timeout=, env=...) gives skills a "
        "confined process to run subprocesses in. cwd is enforced, output "
        "bytes capped, env scrubbed, network screened. The substrate the "
        "coding skill kit runs commands through."
    ),
    "scheduler": (
        "Triggers (cron / interval / event), gates (lock / time / "
        "session-count), and AsyncJobExecutor. Schedule durable jobs that "
        "must survive process restarts. Heartbeats + nightshift windows "
        "(in flight) extend it for quiet-hours background work."
    ),
    "security": (
        "DataMasking applies allow/deny field rules; RBAC/ABAC checks "
        "subject vs resource policy; AuditSigner stamps signed records "
        "for tamper-evident trails."
    ),
    "skills": (
        "Skill protocol = a verb the agent can perform. The coding skill "
        "kit (file ops, shell, run-tests) is the polyglot substrate a "
        "spec→code loop drives. Compose with sandbox + iteration to "
        "build agents that actually execute work."
    ),
    "state": (
        "StateMachine([(STATE, on_enter, on_exit), ...], transitions=). "
        "Domain-neutral FSM you mount on any entity that has lifecycle "
        "(runs, sessions, tasks). Persists via the persistence module."
    ),
    "streaming": (
        "Token/chunk streaming wrappers. Yields the LLM partials with consistent semantics across providers."
    ),
    "tools": (
        "Subclass Tool or @tool a callable; declare a ToolSchema; "
        "register in a ToolRegistry. Agents pick from registries; the "
        "MCP bridge converts schemas to MCP tool definitions."
    ),
    "trust": (
        "Track per-tool / per-skill success ratios. Pair with "
        "improvement to demote unreliable dynamically-generated "
        "components without manual deletion."
    ),
    "validation": (
        "Pydantic-style validators for inputs/outputs at agent and "
        "boundary tool surfaces. Failures convert to Result.fail with a "
        "structured error code."
    ),
}

DESCRIPTIONS: dict[str, str] = {
    "agents": "Agent[Goal, Result] ABC, registry, built-in agents, auction selection",
    "audit": "EventBus subscriber → audit trail, quality trends, anomaly detection",
    "blueprint": "Semantic blueprints for structured generation + harvest flywheel",
    "bootstrap": "create_executor() composition root — wires RuntimeServices",
    "cemaf": "Public API facade — root __init__ curated re-exports",
    "cache": "Result caching with TTL",
    "catalog": "Discover external models and artifacts through typed adapters",
    "citation": "Source citation tracking",
    "cli": "Command-line interface",
    "collision": "TCAS-style coordination — detect & resolve overlapping concurrent writes",
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
    how: str

    def to_payload(self) -> dict[str, str | int]:
        """Compact key form matching the JS contract in cemaf-graph.html."""
        return {
            "id": self.id,
            "loc": self.loc,
            "fi": self.fan_in,
            "fo": self.fan_out,
            "tier": self.tier,
            "d": self.description,
            "h": self.how,
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
    """Map each top-level module name (incl. the root facade) to its source files."""
    modules: dict[str, tuple[Path, ...]] = {}
    for entry in sorted(SRC.iterdir()):
        if entry.is_dir() and entry.name not in EXCLUDED_DIRS:
            modules[entry.name] = tuple(sorted(entry.rglob("*.py")))
        elif entry.name == ROOT_INIT:
            modules[ROOT_PACKAGE] = (entry,)
        elif entry.suffix == ".py":
            modules[entry.stem] = (entry,)
    return modules


def containing_package(source_file: Path) -> tuple[str, ...]:
    """Dotted parts of the package containing source_file, rooted at cemaf."""
    relative = source_file.relative_to(SRC)
    return (ROOT_PACKAGE, *relative.parts[:-1])


def resolve_relative(package: tuple[str, ...], level: int, module: str | None) -> list[str]:
    """Resolve a level-N relative import to absolute dotted parts ([] if invalid)."""
    if level - 1 >= len(package):
        return []
    base = list(package[: len(package) - (level - 1)])
    return base + (module.split(".") if module else [])


def import_targets(tree: ast.AST, known: frozenset[str], package: tuple[str, ...]) -> list[str]:
    """Extract top-level cemaf module names this AST statically imports."""
    targets: list[str] = []

    def add(resolved: list[str], names: list[ast.alias]) -> None:
        if not resolved or resolved[0] != ROOT_PACKAGE:
            return
        if len(resolved) > 1:
            if resolved[1] in known:
                targets.append(resolved[1])
            return
        named_modules = [alias.name for alias in names if alias.name in known]
        if named_modules:
            targets.extend(named_modules)
        else:
            # `from cemaf import <re-exported-symbol>` runs the facade __init__
            targets.append(ROOT_PACKAGE)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                resolved = node.module.split(".") if node.module else []
            else:
                resolved = resolve_relative(package=package, level=node.level, module=node.module)
            add(resolved=resolved, names=node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] != ROOT_PACKAGE:
                    continue
                if len(parts) == 1:
                    # bare `import cemaf` is a dependency on the root facade itself
                    targets.append(ROOT_PACKAGE)
                elif parts[1] in known:
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
            package = containing_package(source_file=source_file)
            for target in import_targets(tree=tree, known=known, package=package):
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
            how=HOW.get(module, ""),
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
    """Splice freshly collected graph data between the HTML data markers.

    With --check, verify the embedded payload is byte-identical to a fresh
    collect() instead of writing (exit 1 on drift).
    """
    data = collect()
    payload = f"{DATA_START}const DATA = {data.to_json()};{DATA_END}"
    html = HTML.read_text(encoding="utf-8")
    if "--check" in sys.argv[1:]:
        if DATA_START not in html or DATA_END not in html:
            raise SystemExit(f"markers {DATA_START}…{DATA_END} not found in {HTML}")
        if payload not in html:
            raise SystemExit(
                f"{HTML.name} graph data is stale — rerun: python docs/architecture/{Path(__file__).name}"
            )
        print(f"{HTML.name} graph data matches source exactly")
        return
    HTML.write_text(splice(html=html, payload=payload), encoding="utf-8")
    print(
        f"wrote {len(data.nodes)} nodes, {len(data.edges)} edges, {data.import_count} imports → {HTML.name}"
    )


if __name__ == "__main__":
    main()
