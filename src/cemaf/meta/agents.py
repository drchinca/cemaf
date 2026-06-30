"""Meta-agents for CEMAF self-introspection, DAG design, code synthesis, and auditing."""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.core.types import JSON, AgentID
from cemaf.memory.manager import MemoryManager
from cemaf.meta.goals import (
    ArchitectGoal,
    ArchitectResult,
    AuditGoal,
    AuditResult,
    DreamGoal,
    DreamResult,
    KnowledgeGraphGoal,
    KnowledgeGraphResult,
    SolutionGoal,
    SolutionResult,
    SynthesizerGoal,
    SynthesizerResult,
)
from cemaf.meta.tools import (
    GenerateDAGTool,
    IntrospectRegistryTool,
    KnowledgeGraphTool,
    TraceAnalyzerTool,
)
from cemaf.scheduler.gates import ExecutionGate, evaluate_gates

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ArchitectAgent
# ---------------------------------------------------------------------------


class ArchitectAgent(Agent[ArchitectGoal, ArchitectResult]):
    """Design DAG pipelines from feature descriptions using registry introspection."""

    def __init__(
        self,
        *,
        introspect_tool: IntrospectRegistryTool,
        generate_dag_tool: GenerateDAGTool,
    ) -> None:
        self._introspect_tool = introspect_tool
        self._generate_dag_tool = generate_dag_tool

    @property
    def id(self) -> AgentID:
        return AgentID("MetaArchitect")

    @property
    def description(self) -> str:
        return "Discovers available agents/tools and designs DAG pipelines for feature descriptions"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: ArchitectGoal,
        context: AgentContext,
    ) -> AgentResult[ArchitectResult]:
        """Introspect registries, select agents, and generate a DAG spec."""
        logger.info("[MetaArchitect] Designing DAG for: %s", goal.feature_description)
        state = AgentState()

        try:
            # 1) Discover available capabilities (including safety metadata)
            introspect_result = await self._introspect_tool.execute(
                registry_type="both",
                query="",
            )
            if not introspect_result.success:
                return AgentResult.fail(
                    error=f"Registry introspection failed: {introspect_result.error}",
                    state=state,
                )

            data = introspect_result.data or {}

            # 2) Analyze tool safety flags for DAG topology decisions
            tools_data: list[JSON] = data.get("tools", [])
            safety_analysis = _analyze_tool_safety(tools=tools_data)

            # 3) Build nodes from discovered agents
            agents_data: list[JSON] = data.get("agents", [])
            nodes: list[JSON] = []
            for idx, agent_info in enumerate(agents_data):
                agent_id = agent_info.get("id", f"agent_{idx}")
                nodes.append(
                    {
                        "id": f"n{idx}",
                        "type": "agent",
                        "name": agent_id,
                        "ref_id": agent_id,
                        "output_key": f"output_{agent_id}",
                    }
                )

            # 4) Build edges: concurrent-safe read-only tools can run in parallel
            edges: list[JSON] = _build_safety_aware_edges(nodes=nodes)

            if not nodes:
                return AgentResult.fail(
                    error="No agents discovered in registries",
                    state=state,
                )

            # 5) Generate the DAG
            dag_name = f"dag_{goal.feature_description[:40].replace(' ', '_').lower()}"
            dag_result = await self._generate_dag_tool.execute(
                name=dag_name,
                description=goal.feature_description,
                nodes=nodes,
                edges=edges,
            )

            if not dag_result.success:
                return AgentResult.fail(
                    error=f"DAG generation failed: {dag_result.error}",
                    state=state,
                )

            rationale_parts = [
                f"Pipeline with {len(nodes)} agent(s) discovered via registry introspection.",
            ]
            if safety_analysis["concurrent_safe"]:
                rationale_parts.append(
                    f"Concurrent-safe tools: {', '.join(safety_analysis['concurrent_safe'])}."
                )
            if safety_analysis["destructive"]:
                rationale_parts.append(
                    f"WARNING: destructive tools detected: {', '.join(safety_analysis['destructive'])}. "
                    f"Require confirmation before execution."
                )

            result = ArchitectResult(
                dag_spec=dag_result.data or {},
                rationale=" ".join(rationale_parts),
            )
            return AgentResult.ok(
                output=result,
                state=state,
            )

        except Exception as exc:
            logger.error("[MetaArchitect] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=f"MetaArchitect error: {exc}", state=state)


# ---------------------------------------------------------------------------
# AgentSynthesizer
# ---------------------------------------------------------------------------

_AGENT_TEMPLATE = textwrap.dedent('''\
    """Generated agent: {agent_name}."""

    from __future__ import annotations

    import logging
    from typing import Any

    from pydantic import BaseModel, Field

    from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
    from cemaf.core.types import AgentID
    from cemaf.skills.base import Skill

    logger = logging.getLogger(__name__)


    class {agent_name}Goal(BaseModel):
        """{description} — input model."""

    {goal_fields}


    class {agent_name}Result(BaseModel):
        """{description} — output model."""

    {result_fields}


    class {agent_name}Agent(Agent[{agent_name}Goal, {agent_name}Result]):
        """{description}."""

        @property
        def id(self) -> AgentID:
            return AgentID("{agent_name}")

        @property
        def description(self) -> str:
            return "{description}"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(
            self,
            goal: {agent_name}Goal,
            context: AgentContext,
        ) -> AgentResult[{agent_name}Result]:
            """Execute the agent."""
            state = AgentState()
            try:
                result = {agent_name}Result()
                return AgentResult.ok(output=result, state=state)
            except Exception as exc:
                logger.error("[{agent_name}] Error: %s", exc, exc_info=True)
                return AgentResult.fail(error=str(exc), state=state)
''')


class AgentSynthesizer(Agent[SynthesizerGoal, SynthesizerResult]):
    """Generate CEMAF agent Python source code from a specification."""

    def __init__(self) -> None:
        pass

    @property
    def id(self) -> AgentID:
        return AgentID("MetaSynthesizer")

    @property
    def description(self) -> str:
        return "Generates Python source code for new CEMAF agents from a spec"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: SynthesizerGoal,
        context: AgentContext,
    ) -> AgentResult[SynthesizerResult]:
        """Generate agent source code from the goal specification."""
        logger.info("[MetaSynthesizer] Generating agent: %s", goal.agent_name)
        state = AgentState()

        try:
            goal_lines = _render_fields(fields=goal.goal_fields, indent=4)
            result_lines = _render_fields(fields=goal.result_fields, indent=4)

            code = _AGENT_TEMPLATE.format(
                agent_name=goal.agent_name,
                description=goal.description,
                goal_fields=goal_lines,
                result_fields=result_lines,
            )

            validation_notes = _validate_generated_code(
                agent_name=goal.agent_name,
                code=code,
            )

            result = SynthesizerResult(
                agent_code=code,
                validation_notes=validation_notes,
            )
            return AgentResult.ok(output=result, state=state)

        except Exception as exc:
            logger.error("[MetaSynthesizer] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=f"MetaSynthesizer error: {exc}", state=state)


def _analyze_tool_safety(*, tools: list[JSON]) -> JSON:
    """Categorize tools by their safety flags for DAG design decisions."""
    concurrent_safe: list[str] = []
    read_only: list[str] = []
    destructive: list[str] = []

    for tool_info in tools:
        name = tool_info.get("name", "")
        safety = tool_info.get("safety", {})
        if safety.get("is_concurrent_safe"):
            concurrent_safe.append(name)
        if safety.get("is_read_only"):
            read_only.append(name)
        if safety.get("is_destructive"):
            destructive.append(name)

    return {
        "concurrent_safe": concurrent_safe,
        "read_only": read_only,
        "destructive": destructive,
    }


def _build_safety_aware_edges(*, nodes: list[JSON]) -> list[JSON]:
    """Build edges for DAG — sequential chain (parallel optimization is DAGExecutor's job)."""
    edges: list[JSON] = []
    for idx in range(len(nodes) - 1):
        edges.append(
            {
                "source": nodes[idx]["id"],
                "target": nodes[idx + 1]["id"],
            }
        )
    return edges


def _render_fields(*, fields: JSON, indent: int) -> str:
    """Render Pydantic field definitions from a dict of {name: type_string}."""
    if not fields:
        return " " * indent + "pass"
    lines: list[str] = []
    prefix = " " * indent
    for field_name, field_type in fields.items():
        lines.append(f'{prefix}{field_name}: {field_type} = Field(description="{field_name}")')
    return "\n".join(lines)


def _validate_generated_code(*, agent_name: str, code: str) -> str:
    """Run basic structural checks on generated agent code."""
    issues: list[str] = []
    if f"class {agent_name}Goal" not in code:
        issues.append(f"Missing {agent_name}Goal class")
    if f"class {agent_name}Result" not in code:
        issues.append(f"Missing {agent_name}Result class")
    if f"class {agent_name}Agent" not in code:
        issues.append(f"Missing {agent_name}Agent class")
    if "async def run" not in code:
        issues.append("Missing async run method")
    if issues:
        return "Issues found: " + "; ".join(issues)
    return "All structural checks passed."


# ---------------------------------------------------------------------------
# AuditAgent
# ---------------------------------------------------------------------------


class AuditAgent(Agent[AuditGoal, AuditResult]):
    """Analyze execution traces using the TraceAnalyzerTool."""

    def __init__(self, *, trace_analyzer_tool: TraceAnalyzerTool) -> None:
        self._trace_analyzer_tool = trace_analyzer_tool

    @property
    def id(self) -> AgentID:
        return AgentID("MetaAuditor")

    @property
    def description(self) -> str:
        return "Deterministic analysis of execution traces for quality and anomaly detection"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: AuditGoal,
        context: AgentContext,
    ) -> AgentResult[AuditResult]:
        """Run trace analysis based on the requested analysis type."""
        logger.info("[MetaAuditor] Running %s analysis", goal.analysis_type)
        state = AgentState()

        try:
            report: JSON = {}
            summary_parts: list[str] = []

            if goal.analysis_type in ("full", "quality"):
                quality_result = await self._trace_analyzer_tool.execute(
                    analysis_type="quality_trend",
                    window=20,
                )
                if quality_result.success:
                    q_data = quality_result.data or {}
                    report["quality_trend"] = q_data
                    trend = q_data.get("trend", [])
                    summary_parts.append(f"Quality trend: {len(trend)} data points")
                else:
                    report["quality_trend_error"] = quality_result.error

            if goal.analysis_type in ("full", "anomalies"):
                anomaly_result = await self._trace_analyzer_tool.execute(
                    analysis_type="anomalies",
                    threshold=2.0,
                )
                if anomaly_result.success:
                    a_data = anomaly_result.data or {}
                    report["anomalies"] = a_data
                    anomaly_count = len(a_data.get("anomalies", []))
                    summary_parts.append(f"Anomalies detected: {anomaly_count}")
                else:
                    report["anomalies_error"] = anomaly_result.error

            if goal.analysis_type == "full" and goal.run_id:
                timeline_result = await self._trace_analyzer_tool.execute(
                    analysis_type="timeline",
                    run_id=goal.run_id,
                )
                if timeline_result.success:
                    t_data = timeline_result.data or []
                    report["timeline"] = t_data
                    summary_parts.append(f"Timeline: {len(t_data)} entries")
                else:
                    report["timeline_error"] = timeline_result.error

            if goal.analysis_type not in ("full", "quality", "anomalies"):
                return AgentResult.fail(
                    error=f"Unknown analysis_type: {goal.analysis_type!r}",
                    state=state,
                )

            summary = "; ".join(summary_parts) if summary_parts else "No data available."
            result = AuditResult(report=report, summary=summary)
            return AgentResult.ok(output=result, state=state)

        except Exception as exc:
            logger.error("[MetaAuditor] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=f"MetaAuditor error: {exc}", state=state)


# ---------------------------------------------------------------------------
# KnowledgeGraphAgent
# ---------------------------------------------------------------------------


class KnowledgeGraphAgent(Agent[KnowledgeGraphGoal, KnowledgeGraphResult]):
    """Manage knowledge graph operations via KnowledgeGraphTool."""

    def __init__(self, *, kg_tool: KnowledgeGraphTool) -> None:
        self._kg_tool = kg_tool

    @property
    def id(self) -> AgentID:
        return AgentID("MetaKnowledgeGraph")

    @property
    def description(self) -> str:
        return "Queries and manages the CEMAF knowledge graph"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: KnowledgeGraphGoal,
        context: AgentContext,
    ) -> AgentResult[KnowledgeGraphResult]:
        """Execute knowledge graph operations."""
        logger.info("[MetaKnowledgeGraph] Operation: %s", goal.operation)
        state = AgentState()

        try:
            if goal.operation == "query":
                return await self._handle_query(goal=goal, state=state)

            if goal.operation == "refresh":
                return await self._handle_refresh(goal=goal, state=state)

            if goal.operation == "stats":
                return await self._handle_stats(state=state)

            return AgentResult.fail(
                error=f"Unknown operation: {goal.operation!r}. Valid: refresh, query, stats",
                state=state,
            )

        except Exception as exc:
            logger.error("[MetaKnowledgeGraph] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=f"MetaKnowledgeGraph error: {exc}", state=state)

    async def _handle_query(
        self,
        *,
        goal: KnowledgeGraphGoal,
        state: AgentState,
    ) -> AgentResult[KnowledgeGraphResult]:
        """Search the knowledge graph by query text."""
        if not goal.query:
            return AgentResult.fail(
                error="query text is required for 'query' operation",
                state=state,
            )

        search_kwargs: dict[str, Any] = {
            "operation": "search",
            "query": goal.query,
        }
        if goal.entity_type is not None:
            search_kwargs["entity_type"] = goal.entity_type

        search_result = await self._kg_tool.execute(**search_kwargs)
        if not search_result.success:
            return AgentResult.fail(
                error=f"Knowledge graph search failed: {search_result.error}",
                state=state,
            )

        entities_data: list[JSON] = search_result.data if isinstance(search_result.data, list) else []
        result = KnowledgeGraphResult(
            entities=tuple(entities_data),
            stats={"query": goal.query, "count": len(entities_data)},
        )
        return AgentResult.ok(output=result, state=state)

    async def _handle_refresh(
        self,
        *,
        goal: KnowledgeGraphGoal,
        state: AgentState,
    ) -> AgentResult[KnowledgeGraphResult]:
        """Refresh by searching with a broad query and returning stats."""
        search_result = await self._kg_tool.execute(
            operation="search",
            query=goal.query or "",
        )

        entities_data: list[JSON] = []
        if search_result.success and isinstance(search_result.data, list):
            entities_data = search_result.data

        result = KnowledgeGraphResult(
            entities=tuple(entities_data),
            stats={"refreshed": True, "entity_count": len(entities_data)},
        )
        return AgentResult.ok(output=result, state=state)

    async def _handle_stats(
        self,
        *,
        state: AgentState,
    ) -> AgentResult[KnowledgeGraphResult]:
        """Return summary statistics from the knowledge graph."""
        # Use a broad single-space query to match all entities (tool requires non-empty query)
        search_result = await self._kg_tool.execute(
            operation="search",
            query=" ",
            limit=10000,
        )

        entity_count = 0
        if search_result.success and isinstance(search_result.data, list):
            entity_count = len(search_result.data)

        result = KnowledgeGraphResult(
            entities=(),
            stats={"total_entities": entity_count},
        )
        return AgentResult.ok(output=result, state=state)


# ---------------------------------------------------------------------------
# DreamAgent — autonomous memory consolidation
# ---------------------------------------------------------------------------


class DreamAgent(Agent[DreamGoal, DreamResult]):
    """Background memory consolidation — orient, gather, consolidate, prune.

    Inspired by Claude Code's 'dream' system. Runs as a standard meta-agent
    gated by optional ExecutionGates (time, session count, lock).
    """

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        gates: tuple[ExecutionGate, ...] = (),
    ) -> None:
        self._memory_manager = memory_manager
        self._gates = gates

    @property
    def id(self) -> AgentID:
        return AgentID("MetaDream")

    @property
    def description(self) -> str:
        return "Autonomous memory consolidation — synthesizes recent signal into durable memories"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: DreamGoal,
        context: AgentContext,
    ) -> AgentResult[DreamResult]:
        """Execute the four-phase dream cycle: orient, gather, consolidate, prune."""
        logger.info("[MetaDream] Starting dream cycle")
        state = AgentState()

        try:
            # Phase 0: Check gates
            if self._gates:
                gate_result = await evaluate_gates(gates=self._gates)
                if not gate_result.all_passed:
                    failed_names = [r.gate_name for r in gate_result.failed_gates]
                    summary = f"Dream deferred — gate(s) blocked: {', '.join(failed_names)}"
                    logger.info("[MetaDream] %s", summary)
                    return AgentResult.ok(
                        output=DreamResult(consolidated_count=0, pruned_count=0, summary=summary),
                        state=state,
                    )

            # Phase 1: Orient — scan existing memories
            from cemaf.memory.semantic import MemoryQuery

            existing = await self._memory_manager.recall(
                query=MemoryQuery(text="", limit=goal.max_consolidations),
            )
            item_count = len(existing)

            if item_count == 0:
                return AgentResult.ok(
                    output=DreamResult(
                        consolidated_count=0,
                        pruned_count=0,
                        summary="No memories to consolidate.",
                    ),
                    state=state,
                )

            # Phase 2: Gather — group recalled items by content signature.
            # Phase 3: Consolidate — for each duplicate-content group keep the
            # highest-confidence item and forget the redundant twins. A real
            # merge: the store genuinely shrinks. consolidated_count counts the
            # items actually removed, not items merely "reviewed".
            consolidated_count = await self._consolidate_duplicates(results=existing)

            # Phase 4: Prune — cleanup expired items
            pruned_count = await self._memory_manager.cleanup()

            summary = (
                f"Dream complete: merged {consolidated_count} redundant memories, "
                f"pruned {pruned_count} stale entries."
            )
            logger.info("[MetaDream] %s", summary)

            return AgentResult.ok(
                output=DreamResult(
                    consolidated_count=consolidated_count,
                    pruned_count=pruned_count,
                    summary=summary,
                ),
                state=state,
            )

        except Exception as exc:
            logger.error("[MetaDream] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=f"MetaDream error: {exc}", state=state)

    async def _consolidate_duplicates(self, *, results: tuple[Any, ...]) -> int:
        """Merge duplicate-content memories; return the count actually removed.

        Items are grouped by a stable signature of their value. Within each
        group the highest-confidence item is kept and the rest are forgotten,
        so redundant memories collapse to one durable record.
        """
        groups: dict[str, list[Any]] = {}
        for result in results:
            item = getattr(result, "item", result)
            # Only items exposing the MemoryItem shape can be merged; anything
            # else (e.g. a bare dict from a non-standard store) is left untouched
            # rather than crashing the dream cycle.
            value = getattr(item, "value", None)
            scope = getattr(item, "scope", None)
            key = getattr(item, "key", None)
            if value is None or scope is None or key is None:
                continue
            signature = self._content_signature(value=value)
            groups.setdefault(signature, []).append(item)

        removed = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            # Keep the highest-confidence item; forget the redundant twins.
            members.sort(key=lambda m: float(getattr(m, "confidence", 1.0)), reverse=True)
            for redundant in members[1:]:
                if await self._memory_manager.forget(scope=redundant.scope, key=redundant.key):
                    removed += 1
        return removed

    @staticmethod
    def _content_signature(*, value: Any) -> str:
        """Stable content signature for duplicate detection."""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)


# ---------------------------------------------------------------------------
# SolutionDesignerAgent — autonomous use-case solver
# ---------------------------------------------------------------------------


class SolutionDesignerAgent(Agent[SolutionGoal, SolutionResult]):
    """Designs, generates, versions, and self-evaluates multi-agent solutions.

    The full self-hosting loop: CEMAF uses its own primitives to solve
    arbitrary use cases by designing DAG architectures and generating agents.
    Solutions are versioned in the KnowledgeGraph for iterative improvement.
    """

    def __init__(
        self,
        *,
        introspect_tool: IntrospectRegistryTool,
        generate_dag_tool: GenerateDAGTool,
        kg_tool: KnowledgeGraphTool,
    ) -> None:
        self._introspect_tool = introspect_tool
        self._generate_dag_tool = generate_dag_tool
        self._kg_tool = kg_tool

    @property
    def id(self) -> AgentID:
        return AgentID("MetaSolutionDesigner")

    @property
    def description(self) -> str:
        return "Autonomous solution designer — designs, generates, and versions multi-agent architectures"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: SolutionGoal,
        context: AgentContext,
    ) -> AgentResult[SolutionResult]:
        """Two-stage design: decompose use case → synthesize domain agents → build DAG."""
        logger.info("[MetaSolutionDesigner] Solving: %s", goal.use_case)
        state = AgentState()

        try:
            # Phase 1: DECOMPOSE — analyze use case into domain agent roles
            roles = _decompose_use_case(
                use_case=goal.use_case,
                constraints=goal.constraints,
            )
            if not roles:
                return AgentResult.fail(error="Could not decompose use case into roles", state=state)

            logger.info(
                "[MetaSolutionDesigner] Decomposed into %d roles: %s", len(roles), [r["name"] for r in roles]
            )

            # Phase 2: SYNTHESIZE — generate agent specs for each role
            generated_agents: list[JSON] = []
            nodes: list[JSON] = []
            for idx, role in enumerate(roles):
                agent_id = role["name"]
                nodes.append(
                    {
                        "id": f"n{idx}",
                        "type": "agent",
                        "name": role["name"],
                        "ref_id": agent_id,
                        "output_key": f"output_{role['name'].lower().replace(' ', '_')}",
                    }
                )
                generated_agents.append(
                    {
                        "id": agent_id,
                        "node_id": f"n{idx}",
                        "role": role["role"],
                        "description": role["description"],
                        "goal_fields": role.get("goal_fields", {}),
                        "result_fields": role.get("result_fields", {}),
                    }
                )

            # Phase 3: BUILD DAG — chain agents with edges
            edges = _build_safety_aware_edges(nodes=nodes)

            dag_name = f"solution_{goal.version_tag}_{goal.use_case[:30].replace(' ', '_').lower()}"
            dag_result = await self._generate_dag_tool.execute(
                name=dag_name,
                description=f"Solution for: {goal.use_case}",
                nodes=nodes,
                edges=edges,
            )

            if not dag_result.success:
                return AgentResult.fail(error=f"DAG generation failed: {dag_result.error}", state=state)

            dag_spec = dag_result.data or {}

            # Phase 4: INTROSPECT for safety analysis
            introspect_result = await self._introspect_tool.execute(registry_type="tools", query="")
            tools_data = (introspect_result.data or {}).get("tools", []) if introspect_result.success else []
            safety = _analyze_tool_safety(tools=tools_data)

            # Phase 5: VERSION — store in knowledge graph
            version_entity = {
                "id": f"solution_{dag_name}",
                "type": "dag",
                "name": dag_name,
                "description": goal.use_case,
                "properties": {
                    "version": goal.version_tag,
                    "use_case": goal.use_case,
                    "roles": [r["name"] for r in roles],
                    "node_count": len(nodes),
                    "constraints": goal.constraints,
                },
            }
            await self._kg_tool.execute(operation="add_entity", entity=version_entity)

            # Phase 6: SELF-EVALUATE
            quality_score = self._assess_quality(
                dag_spec=dag_spec,
                node_count=len(nodes),
                safety=safety,
                constraints=goal.constraints,
                roles=roles,
            )

            rationale = (
                f"Designed {dag_name} with {len(roles)} domain agents: "
                f"{', '.join(r['name'] for r in roles)}. "
                f"Version: {goal.version_tag}. Quality: {quality_score:.2f}."
            )

            result = SolutionResult(
                dag_spec=dag_spec,
                generated_agents=tuple(generated_agents),
                version=goal.version_tag,
                rationale=rationale,
                quality_score=quality_score,
            )

            logger.info("[MetaSolutionDesigner] Solution %s created (score=%.2f)", dag_name, quality_score)
            return AgentResult.ok(output=result, state=state)

        except Exception as exc:
            logger.error("[MetaSolutionDesigner] Error: %s", exc, exc_info=True)
            return AgentResult.fail(error=f"MetaSolutionDesigner error: {exc}", state=state)

    def _assess_quality(
        self,
        *,
        dag_spec: JSON,
        node_count: int,
        safety: JSON,
        constraints: JSON,
        roles: list[JSON] | None = None,
    ) -> float:
        """Deterministic self-assessment of solution quality."""
        score = 0.4  # Base

        # Domain agents (not meta-agents) = better design
        if roles:
            domain_count = sum(1 for r in roles if not r.get("name", "").startswith("Meta"))
            if domain_count >= 2:
                score += 0.15
            if domain_count >= 4:
                score += 0.1

        # DAG has edges = proper chaining
        if dag_spec.get("edges"):
            score += 0.1

        # Constraints respected
        if constraints:
            score += 0.1

        # No destructive tools = safer
        if not safety.get("destructive"):
            score += 0.05

        # Has concurrent-safe tools = parallelizable
        if safety.get("concurrent_safe"):
            score += 0.05

        # Roles have descriptions = well-specified
        if roles and all(r.get("description") for r in roles):
            score += 0.05

        return min(1.0, score)


def _decompose_use_case(*, use_case: str, constraints: JSON) -> list[JSON]:
    """Decompose a use case description into domain-specific agent roles.

    Uses keyword analysis to identify required pipeline phases and
    maps them to agent roles with goal/result field specs.
    """
    text = use_case.lower()
    roles: list[JSON] = []

    # Phase detection via keywords — covers domain + CEMAF-specific terms
    phase_map: list[tuple[list[str], JSON]] = [
        (
            ["transcript", "download", "fetch", "ingest", "scrape", "crawl", "video", "url", "api"],
            {
                "name": "DataIngestor",
                "role": "ingest",
                "description": "Fetches and ingests raw data from external sources",
                "goal_fields": {"source_url": "str", "source_type": "str"},
                "result_fields": {"raw_content": "str", "metadata": "dict[str, Any]"},
            },
        ),
        (
            ["chunk", "split", "segment", "partition", "tokenize", "overlap", "window"],
            {
                "name": "SemanticChunker",
                "role": "chunk",
                "description": "Splits content into semantically coherent chunks with overlap",
                "goal_fields": {"content": "str", "chunk_size": "int", "overlap": "int"},
                "result_fields": {"chunks": "list[dict]", "chunk_count": "int"},
            },
        ),
        (
            ["entity", "extract", "ner", "parse", "structure", "classify", "concept", "fact"],
            {
                "name": "EntityExtractor",
                "role": "extract",
                "description": "Extracts structured entities, facts, and key concepts",
                "goal_fields": {"chunks": "list[dict]", "entity_types": "list[str]"},
                "result_fields": {"entities": "list[dict]", "facts": "list[str]"},
            },
        ),
        (
            [
                "relation",
                "graph",
                "knowledge",
                "connect",
                "link",
                "relate",
                "network",
                "cross-reference",
                "global view",
            ],
            {
                "name": "KnowledgeGraphBuilder",
                "role": "relate",
                "description": "Builds entity-relation knowledge graph from extracted data",
                "goal_fields": {"entities": "list[dict]", "source_id": "str"},
                "result_fields": {"nodes_added": "int", "edges_added": "int"},
            },
        ),
        (
            ["query", "search", "retrieve", "answer", "lookup", "find", "natural language"],
            {
                "name": "QueryResolver",
                "role": "query",
                "description": "Resolves natural language queries against the knowledge base",
                "goal_fields": {"query": "str", "max_results": "int"},
                "result_fields": {"results": "list[dict]", "confidence": "float"},
            },
        ),
        (
            ["summarize", "synthesize", "overview", "digest", "brief", "tldr", "insight"],
            {
                "name": "Synthesizer",
                "role": "synthesize",
                "description": "Produces summaries and synthesized insights from processed data",
                "goal_fields": {"content": "str", "max_length": "int"},
                "result_fields": {"summary": "str", "key_points": "list[str]"},
            },
        ),
        (
            ["evaluate", "score", "assess", "quality", "validate", "check", "gate"],
            {
                "name": "QualityEvaluator",
                "role": "evaluate",
                "description": "Evaluates output quality and provides improvement feedback",
                "goal_fields": {"output": "str", "criteria": "list[str]"},
                "result_fields": {"score": "float", "feedback": "str"},
            },
        ),
        (
            ["store", "persist", "save", "cache", "archive"],
            {
                "name": "PersistenceManager",
                "role": "persist",
                "description": "Manages persistent storage of processed results",
                "goal_fields": {"data": "dict", "scope": "str"},
                "result_fields": {"stored": "bool", "storage_key": "str"},
            },
        ),
        # CEMAF-specific context engineering phases
        (
            ["unify", "context", "resource", "skill", "fragment", "scatter", "uniform", "single"],
            {
                "name": "ContextUnifier",
                "role": "unify",
                "description": "Unifies fragmented memories, resources, and skills into addressable context",
                "goal_fields": {"sources": "list[dict]", "scope": "str"},
                "result_fields": {"unified_context": "dict", "source_count": "int"},
            },
        ),
        (
            ["compact", "compress", "budget", "token", "tier", "surging", "growing", "truncat"],
            {
                "name": "ContextCompactor",
                "role": "compact",
                "description": "Compacts context via tiered storage and token budget management",
                "goal_fields": {"context": "dict", "budget_tokens": "int"},
                "result_fields": {"compacted": "dict", "tokens_saved": "int"},
            },
        ),
        (
            ["audit", "trace", "provenance", "debug", "observable", "transparent", "black box"],
            {
                "name": "AuditTracer",
                "role": "audit",
                "description": "Provides transparent audit trail and provenance tracking for context",
                "goal_fields": {"run_id": "str", "depth": "int"},
                "result_fields": {"audit_trail": "list[dict]", "anomalies": "list[str]"},
            },
        ),
        (
            [
                "dream",
                "consolidat",
                "episode",
                "iteration",
                "task memory",
                "long-term",
                "beyond user",
                "agent memory",
            ],
            {
                "name": "MemoryConsolidator",
                "role": "consolidate",
                "description": "Consolidates episodic and task memory with dream-cycle extraction",
                "goal_fields": {"session_id": "str", "max_items": "int"},
                "result_fields": {"consolidated": "int", "pruned": "int"},
            },
        ),
    ]

    for keywords, role_spec in phase_map:
        if any(kw in text for kw in keywords):
            roles.append(role_spec)

    # Check constraints for explicit phases
    explicit_phases = constraints.get("phases", []) or constraints.get("must_use", [])
    if explicit_phases:
        existing_roles = {r.get("role") for r in roles}
        for phase in explicit_phases:
            phase_lower = str(phase).lower()
            for keywords, role_spec in phase_map:
                if any(kw in phase_lower for kw in keywords) and role_spec["role"] not in existing_roles:
                    roles.append(role_spec)
                    existing_roles.add(role_spec["role"])

    # Fallback: if nothing matched, create a generic 3-agent pipeline
    if not roles:
        roles = [
            {
                "name": "Researcher",
                "role": "research",
                "description": "Gathers and analyzes relevant information",
                "goal_fields": {"topic": "str"},
                "result_fields": {"findings": "str"},
            },
            {
                "name": "Processor",
                "role": "process",
                "description": "Processes and transforms gathered data",
                "goal_fields": {"data": "str"},
                "result_fields": {"processed": "str"},
            },
            {
                "name": "OutputGenerator",
                "role": "output",
                "description": "Generates the final output from processed data",
                "goal_fields": {"processed_data": "str"},
                "result_fields": {"output": "str"},
            },
        ]

    return roles
