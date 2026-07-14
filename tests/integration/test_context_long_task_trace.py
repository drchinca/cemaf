"""Integration coverage for long-task context pull, compression, and tracing."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.audit.factories import create_audit_system
from cemaf.audit.models import AuditEntryType
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.enums import MemoryScope, NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.events.bus import InMemoryEventBus
from cemaf.memory.base import InMemoryStore
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.context_provider import DefaultMemoryContextProvider
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.memory.session import DefaultSessionManager
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.replay.replayer import Replayer, ReplayMode
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _wire_memory_stack() -> tuple[
    DefaultMemoryManager,
    DefaultMemoryContextProvider,
    DefaultSessionManager,
]:
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()
    semantic_store = DefaultSemanticMemoryStore(
        memory_store=InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    memory_manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=InMemoryEpisodicStore(),
    )
    compactor = SimpleMemoryCompactor(scorer=scorer)
    compiler = PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=3.5))
    provider = DefaultMemoryContextProvider(
        memory_manager=memory_manager,
        compactor=compactor,
        compiler=compiler,
        token_estimator=SimpleTokenEstimator(chars_per_token=3.5),
    )
    session_manager = DefaultSessionManager(
        memory_manager=memory_manager,
        compactor=compactor,
    )
    return memory_manager, provider, session_manager


class _TaskGoal(BaseModel):
    task: str
    payload: dict[str, Any] | None = None


class _TaskResult(BaseModel):
    stage: str
    task: str
    inherited_stage: str | None = None
    memory_keys: list[str]
    compiled_context_chars: int
    summary: str


class _TraceAgent(Agent[_TaskGoal, _TaskResult]):
    def __init__(self, *, agent_name: str, stage: str) -> None:
        self._agent_name = agent_name
        self._stage = stage

    @property
    def id(self) -> AgentID:
        return AgentID(self._agent_name)

    @property
    def description(self) -> str:
        return f"Deterministic {self._stage} agent for context-trace tests"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _TaskGoal, context: AgentContext) -> AgentResult[_TaskResult]:
        compiled_messages = context.artifacts.get("compiled_context", [])
        compiled_text = "\n".join(
            str(message.get("content", "")) for message in compiled_messages if isinstance(message, dict)
        )
        inherited_stage = None
        if goal.payload is not None:
            inherited_stage = (
                str(goal.payload.get("stage")) if goal.payload.get("stage") is not None else None
            )

        memory_keys = sorted(str(key) for key in context.global_memory)
        result = _TaskResult(
            stage=self._stage,
            task=goal.task,
            inherited_stage=inherited_stage,
            memory_keys=memory_keys,
            compiled_context_chars=len(compiled_text),
            summary=f"{self._stage} handled {goal.task} after {inherited_stage or 'seed'}",
        )
        return AgentResult.ok(
            output=result,
            state=AgentState(),
            metadata={
                "seen_memory_keys": memory_keys,
                "compiled_context_chars": len(compiled_text),
            },
        )


class _SeedGoal(BaseModel):
    request: str


class _SeedResult(BaseModel):
    topic: str
    route_hint: str


class _SeedAgent(Agent[_SeedGoal, _SeedResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("SeedAgent")

    @property
    def description(self) -> str:
        return "Seeds the workflow with a topic and route hint"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _SeedGoal, context: AgentContext) -> AgentResult[_SeedResult]:
        return AgentResult.ok(
            output=_SeedResult(topic="launch", route_hint="publish_path"),
            state=AgentState(),
        )


class _ResearchGoal(BaseModel):
    topic: str


class _ResearchResult(BaseModel):
    research: str


class _ResearchAgent(Agent[_ResearchGoal, _ResearchResult]):
    def __init__(self) -> None:
        self.seen_topics: list[str] = []

    @property
    def id(self) -> AgentID:
        return AgentID("ParallelResearchAgent")

    @property
    def description(self) -> str:
        return "Produces a deterministic research result"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _ResearchGoal, context: AgentContext) -> AgentResult[_ResearchResult]:
        self.seen_topics.append(goal.topic)
        return AgentResult.ok(
            output=_ResearchResult(research="market ready"),
            state=AgentState(),
        )


class _RiskGoal(BaseModel):
    topic: str


class _RiskResult(BaseModel):
    risks: str


class _RiskAgent(Agent[_RiskGoal, _RiskResult]):
    def __init__(self) -> None:
        self.seen_topics: list[str] = []

    @property
    def id(self) -> AgentID:
        return AgentID("ParallelRiskAgent")

    @property
    def description(self) -> str:
        return "Produces a deterministic risk result"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _RiskGoal, context: AgentContext) -> AgentResult[_RiskResult]:
        self.seen_topics.append(goal.topic)
        return AgentResult.ok(
            output=_RiskResult(risks="compliance gate"),
            state=AgentState(),
        )


class _PublishGoal(BaseModel):
    topic: str
    research: str
    risks: str


class _PublishResult(BaseModel):
    summary: str


class _PublishAgent(Agent[_PublishGoal, _PublishResult]):
    def __init__(self) -> None:
        self.seen_inputs: list[tuple[str, str, str]] = []

    @property
    def id(self) -> AgentID:
        return AgentID("PublishAgent")

    @property
    def description(self) -> str:
        return "Publishes the selected branch output"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _PublishGoal, context: AgentContext) -> AgentResult[_PublishResult]:
        self.seen_inputs.append((goal.topic, goal.research, goal.risks))
        return AgentResult.ok(
            output=_PublishResult(summary=f"{goal.topic}|{goal.research}|{goal.risks}"),
            state=AgentState(),
        )


class _ArchiveGoal(BaseModel):
    topic: str


class _ArchiveResult(BaseModel):
    summary: str


class _ArchiveAgent(Agent[_ArchiveGoal, _ArchiveResult]):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def id(self) -> AgentID:
        return AgentID("ArchiveAgent")

    @property
    def description(self) -> str:
        return "Fallback branch that should stay idle in this scenario"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _ArchiveGoal, context: AgentContext) -> AgentResult[_ArchiveResult]:
        self.calls += 1
        return AgentResult.ok(
            output=_ArchiveResult(summary=f"archive:{goal.topic}"),
            state=AgentState(),
        )


def _register_trace_pipeline(registry: AgentRegistry) -> None:
    for agent_name, stage in (
        ("Planner", "planner"),
        ("Drafter", "drafter"),
        ("Reviewer", "reviewer"),
        ("Publisher", "publisher"),
    ):
        registry.register_agent(
            agent_instance=_TraceAgent(agent_name=agent_name, stage=stage),
            goal_type=_TaskGoal,
        )


def _long_task_dag(task: str) -> DAG:
    plan = Node(
        id=NodeID("plan"),
        type=NodeType.AGENT,
        name="plan",
        ref_id="Planner",
        input_mapping={"task": task},
        output_key="plan",
        structured_output=True,
        retry_on_failure=False,
    )
    draft = Node(
        id=NodeID("draft"),
        type=NodeType.AGENT,
        name="draft",
        ref_id="Drafter",
        input_mapping={"task": task, "payload": "$$plan$$"},
        output_key="draft",
        structured_output=True,
        retry_on_failure=False,
    )
    review = Node(
        id=NodeID("review"),
        type=NodeType.AGENT,
        name="review",
        ref_id="Reviewer",
        input_mapping={"task": task, "payload": "$$draft$$"},
        output_key="review",
        structured_output=True,
        retry_on_failure=False,
    )
    publish = Node(
        id=NodeID("publish"),
        type=NodeType.AGENT,
        name="publish",
        ref_id="Publisher",
        input_mapping={"task": task, "payload": "$$review$$"},
        output_key="publication",
        structured_output=True,
        retry_on_failure=False,
    )
    return DAG(
        name="long-task-context-trace",
        nodes=(plan, draft, review, publish),
        edges=(
            Edge(source=plan.id, target=draft.id),
            Edge(source=draft.id, target=review.id),
            Edge(source=review.id, target=publish.id),
        ),
        entry_node=plan.id,
    )


async def _seed_long_task_memory(manager: DefaultMemoryManager) -> dict[str, int]:
    seeded = {
        "customer_constraints": {
            "brief": (
                "Customer constraints: preserve formal tone, mention launch timing, "
                "surface operational risk, include governance language, and keep the "
                "narrative grounded in the migration plan. "
            )
            * 4
        },
        "risk_register": {
            "brief": (
                "Risk register: legacy data gaps, integration rollback windows, "
                "sign-off dependencies, and reviewer scrutiny from compliance. "
            )
            * 4
        },
    }
    for key, value in seeded.items():
        await manager.remember(
            scope=MemoryScope.TENANT,
            key=key,
            value=value,
            content_for_embedding=f"{key} launch narrative customer constraints deadline risks",
        )
    return {key: len(str(value)) for key, value in seeded.items()}


async def _seed_scope_memories(manager: DefaultMemoryManager) -> None:
    await manager.remember(
        scope=MemoryScope.TENANT,
        key="workspace_guardrails",
        value={"text": "Workspace guardrails: formal tone, board-ready narrative."},
        content_for_embedding="workspace launch guardrails formal narrative",
    )
    await manager.remember(
        scope=MemoryScope.PROJECT,
        key="project_plan",
        value={"text": "Project plan: launch sequence, milestones, delivery windows."},
        content_for_embedding="project launch plan milestones delivery windows",
    )
    await manager.remember(
        scope=MemoryScope.USER,
        key="user_preference",
        value={"text": "User preference: concise bullets, risks first, no hype."},
        content_for_embedding="user preference concise bullets risks first",
    )


@pytest.mark.asyncio
async def test_context_pull_is_compacted_to_fit_budget() -> None:
    manager, provider, _session_manager = _wire_memory_stack()
    raw_content_lengths: list[int] = []
    for idx in range(5):
        value = {
            "detail": (
                f"Long task memory {idx} about launch constraints, reviewers, and delivery sequencing. "
            )
            * 12
        }
        raw_content_lengths.append(len(str(value)))
        await manager.remember(
            scope=MemoryScope.TENANT,
            key=f"task_memory_{idx}",
            value=value,
            content_for_embedding="launch constraints reviewers delivery sequencing",
        )

    sources = await provider.provide_context_sources(
        query=MemoryQuery(text="launch constraints reviewers delivery sequencing", limit=10),
        token_budget=80,
    )

    assert sources
    assert sum(source.token_count or 0 for source in sources) <= 80
    pulled_ids = {source.source_id for source in sources}
    assert pulled_ids <= {f"tenant:task_memory_{idx}" for idx in range(5)}
    assert sum(len(source.content) for source in sources) < sum(raw_content_lengths)
    assert any(source.content.endswith("...") or source.content.startswith("[tenant:") for source in sources)


@pytest.mark.asyncio
async def test_long_dag_preserves_context_flow_and_traceability() -> None:
    manager, _provider, session_manager = _wire_memory_stack()
    raw_memory_sizes = await _seed_long_task_memory(manager)
    task = "launch narrative customer constraints deadline risks"

    registry = AgentRegistry()
    _register_trace_pipeline(registry)

    event_bus = InMemoryEventBus()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    run_logger = InMemoryRunLogger()
    token_budget = TokenBudget(max_tokens=150, reserved_for_output=30)
    compiler = PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=3.5))

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            run_logger=run_logger,
            event_bus=event_bus,
            memory_manager=manager,
            session_manager=session_manager,
            context_compiler=compiler,
            token_budget=token_budget,
        ),
    )

    result = await executor.run(dag=_long_task_dag(task))

    assert result.status == RunStatus.COMPLETED
    assert len(result.node_results) == 4
    assert result.final_context is not None
    assert result.final_context.get("plan.stage") == "planner"
    assert result.final_context.get("draft.inherited_stage") == "planner"
    assert result.final_context.get("review.inherited_stage") == "drafter"
    assert result.final_context.get("publication.inherited_stage") == "reviewer"

    by_node = {str(node_result.node_id): node_result for node_result in result.node_results}
    first_node = by_node["plan"]
    later_memory_keys = {
        key
        for node_id in ("draft", "review", "publish")
        for key in by_node[node_id].metadata.get("seen_memory_keys", [])
    }

    assert "customer_constraints" in first_node.metadata.get("seen_memory_keys", [])
    assert "risk_register" in first_node.metadata.get("seen_memory_keys", [])
    assert "Planner_output" in later_memory_keys
    assert first_node.metadata.get("compiled_context_chars", 0) > 0
    assert first_node.metadata["compiled_context_chars"] < sum(raw_memory_sizes.values())

    timeline = result.final_context.get_timeline()
    assert [patch.path for patch in timeline] == ["plan", "draft", "review", "publication"]
    assert all(patch.correlation_id == str(result.run_id) for patch in timeline)

    record = run_logger.get_record(str(result.run_id))
    assert record is not None
    assert [patch.path for patch in record.patches] == ["plan", "draft", "review", "publication"]
    assert record.provenance_chain is not None
    assert [str(link.node_id) for link in record.provenance_chain.links] == [
        "plan",
        "draft",
        "review",
        "publish",
    ]
    assert all(link.context_hash for link in record.provenance_chain.links)

    timeline_entries = await audit_trail.get_run_timeline(str(result.run_id))
    node_entries = [entry for entry in timeline_entries if entry.type == AuditEntryType.NODE_EXECUTED]
    assert [str(entry.payload.get("node_id")) for entry in node_entries] == [
        "plan",
        "draft",
        "review",
        "publish",
    ]
    assert all(entry.payload.get("run_id") == str(result.run_id) for entry in node_entries)


@pytest.mark.asyncio
async def test_scope_filtered_compilation_respects_memory_levels() -> None:
    """TENANT/PROJECT/USER behave as distinct context levels when queried explicitly."""
    manager, provider, session_manager = _wire_memory_stack()
    await _seed_scope_memories(manager)
    await session_manager.bootstrap(session_id="scope-levels")
    await session_manager.ingest(
        session_id="scope-levels",
        key="session_transcript",
        value={"text": "Session transcript: transient draft and TODO list."},
    )

    budget = TokenBudget(max_tokens=800, reserved_for_output=100)
    tenant_compiled = await provider.compile_with_memories(
        artifacts=(),
        memory_query=MemoryQuery(scope=MemoryScope.TENANT, limit=10),
        budget=budget,
    )
    project_compiled = await provider.compile_with_memories(
        artifacts=(),
        memory_query=MemoryQuery(scope=MemoryScope.PROJECT, limit=10),
        budget=budget,
    )
    user_compiled = await provider.compile_with_memories(
        artifacts=(),
        memory_query=MemoryQuery(scope=MemoryScope.USER, limit=10),
        budget=budget,
    )
    session_compiled = await provider.compile_with_memories(
        artifacts=(),
        memory_query=MemoryQuery(
            scope=MemoryScope.SESSION,
            limit=10,
            session_id="scope-levels",
        ),
        budget=budget,
    )

    assert {source.source_id for source in tenant_compiled.sources if source.source_type == "memory"} == {
        "tenant:workspace_guardrails"
    }
    assert {source.source_id for source in project_compiled.sources if source.source_type == "memory"} == {
        "project:project_plan"
    }
    assert {source.source_id for source in user_compiled.sources if source.source_type == "memory"} == {
        "user:user_preference"
    }
    assert {source.source_id for source in session_compiled.sources if source.source_type == "memory"} == {
        "session:session_transcript"
    }

    await session_manager.dispose(session_id="scope-levels")


@pytest.mark.asyncio
async def test_priority_budget_keeps_high_value_context_across_artifacts_and_memories() -> None:
    """When the budget is tight, explicit priorities decide what survives."""
    manager, provider, _session_manager = _wire_memory_stack()
    compiler = PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=3.5))

    await manager.remember(
        scope=MemoryScope.PROJECT,
        key="durable_policy",
        value={"text": "Durable project policy: mention blockers, fallback plan, and owner names."},
        content_for_embedding="durable project policy blockers fallback owner names",
    )
    await manager.remember(
        scope=MemoryScope.PROJECT,
        key="verbose_notes",
        value={
            "text": (
                "Verbose notes: exploratory language, discarded hypotheses, "
                "and long background context that should lose under budget pressure. "
            )
            * 8
        },
        content_for_embedding="verbose exploratory background context discarded hypotheses",
    )

    memories = await provider.provide_memories_for_compiler(
        query=MemoryQuery(scope=MemoryScope.PROJECT, limit=10),
        token_budget=500,
    )
    compiled = await compiler.compile(
        artifacts=(
            ("directive", "Directive: lead with risks, then decisions, then owners."),
            ("background", ("Background context: " + "history " * 70).strip()),
        ),
        memories=memories,
        budget=TokenBudget(max_tokens=90, reserved_for_output=10),
        priorities={
            "directive": 100,
            "background": 1,
            "project:durable_policy": 90,
            "project:verbose_notes": 0,
        },
    )

    selected_ids = {source.source_id for source in compiled.sources}
    assert "directive" in selected_ids
    assert "project:durable_policy" in selected_ids
    assert "background" not in selected_ids
    assert "project:verbose_notes" not in selected_ids
    assert compiled.total_tokens <= compiled.budget.available_tokens


@pytest.mark.asyncio
async def test_reused_executor_does_not_leak_session_memory_between_runs() -> None:
    """Sequential runs keep durable memory but do not leak session outputs across runtimes."""
    manager, _provider, session_manager = _wire_memory_stack()
    await _seed_scope_memories(manager)

    registry = AgentRegistry()
    _register_trace_pipeline(registry)

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(
            memory_manager=manager,
            session_manager=session_manager,
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=220, reserved_for_output=40),
        ),
    )

    first = await executor.run(dag=_long_task_dag("workspace launch guardrails project plan user preference"))
    assert first.status == RunStatus.COMPLETED
    assert await manager.recall(query=MemoryQuery(scope=MemoryScope.SESSION, limit=100)) == ()

    second = await executor.run(
        dag=_long_task_dag("workspace launch guardrails project plan user preference")
    )
    assert second.status == RunStatus.COMPLETED

    first_node_second_run = next(
        node_result for node_result in second.node_results if str(node_result.node_id) == "plan"
    )
    seen_memory = set(first_node_second_run.metadata.get("seen_memory_keys", []))
    assert {"workspace_guardrails", "project_plan", "user_preference"} <= seen_memory
    assert "Planner_output" not in seen_memory
    assert "Drafter_output" not in seen_memory
    assert "Reviewer_output" not in seen_memory
    assert "Publisher_output" not in seen_memory


@pytest.mark.asyncio
async def test_promoted_session_memory_carries_into_future_runs_with_durable_levels() -> None:
    """Session memory promoted to PROJECT survives and joins future durable context."""
    manager, _provider, session_manager = _wire_memory_stack()
    await _seed_scope_memories(manager)

    await session_manager.bootstrap(session_id="promotion-seed")
    await session_manager.ingest(
        session_id="promotion-seed",
        key="carry_forward",
        value={"text": "Carry forward: last run discovered a launch dependency on compliance."},
        confidence=0.95,
    )
    removed = await session_manager.dispose(
        session_id="promotion-seed",
        promote_to=MemoryScope.PROJECT,
        promotion_min_confidence=0.7,
    )
    assert removed >= 1

    project_keys = {
        result.item.key
        for result in await manager.recall(query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100))
    }
    assert "carry_forward" in project_keys

    registry = AgentRegistry()
    _register_trace_pipeline(registry)

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(
            memory_manager=manager,
            session_manager=session_manager,
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=220, reserved_for_output=40),
        ),
    )

    result = await executor.run(
        dag=_long_task_dag("workspace launch guardrails project plan user preference compliance")
    )
    assert result.status == RunStatus.COMPLETED

    first_node = next(
        node_result for node_result in result.node_results if str(node_result.node_id) == "plan"
    )
    seen_memory = set(first_node.metadata.get("seen_memory_keys", []))
    assert {"workspace_guardrails", "project_plan", "user_preference", "carry_forward"} <= seen_memory


@pytest.mark.asyncio
async def test_parallel_fanout_then_router_carries_context_into_only_selected_branch() -> None:
    """Real executor path: AGENT fan-out survives fan-in and only the routed branch runs."""
    manager, _provider, session_manager = _wire_memory_stack()
    event_bus = InMemoryEventBus()
    audit_log, audit_trail = create_audit_system(event_bus=event_bus)
    run_logger = InMemoryRunLogger()
    compiler = PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=3.5))

    seed_agent = _SeedAgent()
    research_agent = _ResearchAgent()
    risk_agent = _RiskAgent()
    publish_agent = _PublishAgent()
    archive_agent = _ArchiveAgent()

    registry = AgentRegistry()
    registry.register_agent(agent_instance=seed_agent, goal_type=_SeedGoal)
    registry.register_agent(agent_instance=research_agent, goal_type=_ResearchGoal)
    registry.register_agent(agent_instance=risk_agent, goal_type=_RiskGoal)
    registry.register_agent(agent_instance=publish_agent, goal_type=_PublishGoal)
    registry.register_agent(agent_instance=archive_agent, goal_type=_ArchiveGoal)

    start = Node(
        id=NodeID("start"),
        type=NodeType.AGENT,
        name="start",
        ref_id="SeedAgent",
        output_key="seed",
        input_mapping={"request": "launch memo"},
        structured_output=True,
        retry_on_failure=False,
    )
    parallel = Node(
        id=NodeID("parallel"),
        type=NodeType.PARALLEL,
        name="parallel",
        parallel_nodes=(NodeID("branch_research"), NodeID("branch_risk")),
        output_key="parallel_report",
        retry_on_failure=False,
    )
    branch_research = Node(
        id=NodeID("branch_research"),
        type=NodeType.AGENT,
        name="branch_research",
        ref_id="ParallelResearchAgent",
        input_mapping={"topic": "$$seed.topic$$"},
        output_key="research_result",
        structured_output=True,
        retry_on_failure=False,
    )
    branch_risk = Node(
        id=NodeID("branch_risk"),
        type=NodeType.AGENT,
        name="branch_risk",
        ref_id="ParallelRiskAgent",
        input_mapping={"topic": "$$seed.topic$$"},
        output_key="risk_result",
        structured_output=True,
        retry_on_failure=False,
    )
    router = Node(
        id=NodeID("router"),
        type=NodeType.ROUTER,
        name="router",
        routes={"publish_path": "publish", "archive_path": "archive"},
        config={
            "route_fn": lambda data: (
                "publish_path" if data.get("research_result") and data.get("risk_result") else "archive_path"
            )
        },
        output_key="route_taken",
    )
    publish = Node(
        id=NodeID("publish"),
        type=NodeType.AGENT,
        name="publish",
        ref_id="PublishAgent",
        input_mapping={
            "topic": "$$seed.topic$$",
            "research": "$$research_result.research$$",
            "risks": "$$risk_result.risks$$",
        },
        output_key="publication",
        structured_output=True,
        retry_on_failure=False,
    )
    archive = Node(
        id=NodeID("archive"),
        type=NodeType.AGENT,
        name="archive",
        ref_id="ArchiveAgent",
        input_mapping={"topic": "$$seed.topic$$"},
        output_key="archive_note",
        structured_output=True,
        retry_on_failure=False,
    )

    dag = DAG(
        name="parallel-router-carry",
        nodes=(start, parallel, branch_research, branch_risk, router, publish, archive),
        edges=(
            Edge(source=start.id, target=parallel.id),
            Edge(source=parallel.id, target=branch_research.id),
            Edge(source=parallel.id, target=branch_risk.id),
            Edge(source=parallel.id, target=router.id),
            Edge(source=router.id, target=publish.id),
            Edge(source=router.id, target=archive.id),
        ),
        entry_node=start.id,
    )

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            run_logger=run_logger,
            event_bus=event_bus,
            memory_manager=manager,
            session_manager=session_manager,
            context_compiler=compiler,
            token_budget=TokenBudget(max_tokens=220, reserved_for_output=40),
        ),
    )
    result = await executor.run(dag=dag)

    assert result.status == RunStatus.COMPLETED
    assert result.final_context.get("research_result.research") == "market ready"
    assert result.final_context.get("risk_result.risks") == "compliance gate"
    assert result.final_context.get("publication.summary") == "launch|market ready|compliance gate"
    assert result.final_context.get("archive_note") is None
    assert research_agent.seen_topics == ["launch"]
    assert risk_agent.seen_topics == ["launch"]
    assert publish_agent.seen_inputs == [("launch", "market ready", "compliance gate")]
    assert archive_agent.calls == 0

    record = run_logger.get_record(str(result.run_id))
    assert record is not None
    patch_paths = [patch.path for patch in record.patches]
    assert "research_result" in patch_paths
    assert "risk_result" in patch_paths
    assert "parallel_report" in patch_paths
    assert "route_taken" in patch_paths
    assert "publication" in patch_paths
    assert [str(link.node_id) for link in record.provenance_chain.links] == [
        "start",
        "branch_research",
        "branch_risk",
        "publish",
    ]

    timeline_entries = await audit_trail.get_run_timeline(str(result.run_id))
    node_entries = [entry for entry in timeline_entries if entry.type == AuditEntryType.NODE_EXECUTED]
    node_ids = [str(entry.payload.get("node_id")) for entry in node_entries]
    assert "archive" not in node_ids
    assert {"start", "parallel", "router", "publish"} <= set(node_ids)


@pytest.mark.asyncio
async def test_memory_evolution_across_many_runs_accumulates_high_confidence_durable_context() -> None:
    """Durable memory can grow across runs while low-confidence noise is filtered out."""
    manager, _provider, session_manager = _wire_memory_stack()
    await _seed_scope_memories(manager)

    await session_manager.bootstrap(session_id="evolution-1")
    await session_manager.ingest(
        session_id="evolution-1",
        key="compliance_dependency",
        value={"text": "Launch dependency: compliance sign-off blocks release readiness."},
        confidence=0.95,
    )
    await session_manager.dispose(
        session_id="evolution-1",
        promote_to=MemoryScope.PROJECT,
        promotion_min_confidence=0.7,
    )

    await session_manager.bootstrap(session_id="evolution-2")
    await session_manager.ingest(
        session_id="evolution-2",
        key="transient_chatter",
        value={"text": "Unreliable chatter with no durable operational value."},
        confidence=0.3,
    )
    await session_manager.dispose(
        session_id="evolution-2",
        promote_to=MemoryScope.PROJECT,
        promotion_min_confidence=0.7,
    )

    await session_manager.bootstrap(session_id="evolution-3")
    await session_manager.ingest(
        session_id="evolution-3",
        key="stakeholder_escalation",
        value={"text": "Stakeholder escalation: finance approver must be looped in before launch."},
        confidence=0.93,
    )
    await session_manager.dispose(
        session_id="evolution-3",
        promote_to=MemoryScope.PROJECT,
        promotion_min_confidence=0.7,
    )

    registry = AgentRegistry()
    _register_trace_pipeline(registry)

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(
            memory_manager=manager,
            session_manager=session_manager,
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=260, reserved_for_output=40),
        ),
    )

    result = await executor.run(
        dag=_long_task_dag("launch compliance stakeholder workspace project user readiness")
    )

    assert result.status == RunStatus.COMPLETED
    first_node = next(
        node_result for node_result in result.node_results if str(node_result.node_id) == "plan"
    )
    seen_memory = set(first_node.metadata.get("seen_memory_keys", []))
    assert {"workspace_guardrails", "project_plan", "user_preference"} <= seen_memory
    assert "compliance_dependency" in seen_memory
    assert "stakeholder_escalation" in seen_memory
    assert "transient_chatter" not in seen_memory


@pytest.mark.asyncio
async def test_real_framework_run_replays_exact_final_context_from_patches() -> None:
    """RunLogger patch history from a real executor run is sufficient for deterministic replay."""
    manager, _provider, session_manager = _wire_memory_stack()
    await _seed_long_task_memory(manager)
    event_bus = InMemoryEventBus()
    run_logger = InMemoryRunLogger()

    registry = AgentRegistry()
    _register_trace_pipeline(registry)

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            run_logger=run_logger,
            event_bus=event_bus,
            memory_manager=manager,
            session_manager=session_manager,
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=180, reserved_for_output=30),
        ),
    )

    result = await executor.run(dag=_long_task_dag("launch narrative customer constraints deadline risks"))

    assert result.status == RunStatus.COMPLETED
    record = run_logger.get_record(str(result.run_id))
    assert record is not None
    assert record.final_context is not None
    assert len(record.patches) == len(result.final_context.get_timeline())

    replayer = Replayer(record)
    replay_result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

    assert replay_result.success
    assert replay_result.patches_applied == len(record.patches)
    assert replay_result.final_context.data == result.final_context.data
    assert len(replay_result.final_context.get_timeline()) == len(result.final_context.get_timeline())

    state = await session_manager.get_state(session_id=str(result.run_id))
    assert state is not None
    assert state.phase.value == "disposed"


@pytest.mark.asyncio
async def test_real_framework_event_stream_tracks_long_dag_nodes_with_single_correlation() -> None:
    """EventBus emits exact long-DAG lifecycle with stable run correlation and node payloads."""
    manager, _provider, session_manager = _wire_memory_stack()
    await _seed_scope_memories(manager)
    event_bus = InMemoryEventBus()
    seen_events: list[tuple[str, str | None, dict[str, Any]]] = []

    def _capture(event: Any) -> None:
        seen_events.append((event.type, event.correlation_id, dict(event.payload)))

    event_bus.subscribe_all(_capture)

    registry = AgentRegistry()
    _register_trace_pipeline(registry)

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            event_bus=event_bus,
            memory_manager=manager,
            session_manager=session_manager,
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=220, reserved_for_output=40),
        ),
    )

    result = await executor.run(
        dag=_long_task_dag("workspace launch guardrails project plan user preference")
    )

    assert result.status == RunStatus.COMPLETED
    run_id = str(result.run_id)

    dag_started = [
        payload for etype, corr, payload in seen_events if etype == "dag.started" and corr == run_id
    ]
    dag_completed = [
        payload for etype, corr, payload in seen_events if etype == "dag.completed" and corr == run_id
    ]
    task_started = [
        payload for etype, corr, payload in seen_events if etype == "task.started" and corr == run_id
    ]
    task_completed = [
        payload for etype, corr, payload in seen_events if etype == "task.completed" and corr == run_id
    ]

    assert len(dag_started) == 1
    assert len(dag_completed) == 1
    assert [payload["node_id"] for payload in task_started] == ["plan", "draft", "review", "publish"]
    assert [payload["node_id"] for payload in task_completed] == ["plan", "draft", "review", "publish"]
    assert all(payload["run_id"] == run_id for payload in task_completed)
    assert task_started[0]["goal_text"] == "workspace launch guardrails project plan user preference"
    assert task_started[1]["inputs"]["payload"]["stage"] == "planner"
    assert task_started[2]["inputs"]["payload"]["stage"] == "drafter"
    assert task_started[3]["inputs"]["payload"]["stage"] == "reviewer"
