"""Meta-agents for CEMAF self-introspection, DAG design, code synthesis, and auditing."""

from __future__ import annotations

import logging
import textwrap
from typing import Any

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.core.types import JSON, AgentID
from cemaf.meta.goals import (
    ArchitectGoal,
    ArchitectResult,
    AuditGoal,
    AuditResult,
    KnowledgeGraphGoal,
    KnowledgeGraphResult,
    SynthesizerGoal,
    SynthesizerResult,
)
from cemaf.meta.tools import (
    GenerateDAGTool,
    IntrospectRegistryTool,
    KnowledgeGraphTool,
    TraceAnalyzerTool,
)

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
