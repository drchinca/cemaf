"""RECOVER end-to-end: a POST gate asks for retry-with-feedback; agent uses it.

Closes the next-tier gap from the LLM-systems review: today a gate-reject
forecloses the highest-value retry case (revise output against eval feedback).
With RECOVER, the executor re-runs the agent with the eval reason surfaced under
``agent_context.global_memory["recovery_hints"]`` — the agent reads it and corrects.

Bounded by ``ContextNodeExecutor(max_recovery_attempts=...)`` so a deterministic
gate cannot loop forever.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.context.context import Context
from cemaf.core.types import AgentID, NodeID
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.interceptors import (
    GateEvalInterceptor,
    GateFailureMode,
    create_interceptor_pipeline,
)
from cemaf.interceptors.types import RECOVERY_HINTS_KEY
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _DraftGoal(BaseModel):
    pass


class _LearningWriter:
    """Emits a short draft on first attempt; emits a long one once it sees a hint.

    Models the real production case: an LLM agent that revises its output when
    given eval feedback. Tracks attempts so we can prove no-burn semantics.
    """

    def __init__(self) -> None:
        self.attempts = 0
        self.last_hints: list[dict[str, object]] = []

    @property
    def id(self) -> AgentID:
        return AgentID("Writer")

    @property
    def description(self) -> str:
        return "writer"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _DraftGoal, context: AgentContext) -> AgentResult[str]:
        self.attempts += 1
        hints = context.global_memory.get(RECOVERY_HINTS_KEY, [])
        self.last_hints = list(hints) if isinstance(hints, list) else []
        # If a length hint arrived, comply.
        if any(h.get("code") == "length" for h in self.last_hints):
            return AgentResult.ok(output="x" * 200, state=AgentState())
        return AgentResult.ok(output="too short", state=AgentState())


def _executor_with_writer(*, max_recovery_attempts: int) -> tuple[DAGExecutor, _LearningWriter]:
    writer = _LearningWriter()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=writer, goal_type=_DraftGoal)

    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="write",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        )
    )
    # Build the executor manually so we can pass max_recovery_attempts.
    node_executor = ContextNodeExecutor(
        agent_registry=registry,
        interceptor_pipeline=pipeline,
        max_recovery_attempts=max_recovery_attempts,
    )
    services = RuntimeServices(interceptor_pipeline=pipeline)
    dag_executor = DAGExecutor(
        node_executor=node_executor,
        services=services,
        config=ExecutorConfig(enable_events=False),
    )
    return dag_executor, writer


def _dag() -> DAG:
    write = Node.agent(id="write", name="write", agent_id="Writer", output_key="draft")
    return DAG(
        name="recover-dag",
        nodes=(write,),
        edges=(),
        entry_node=NodeID("write"),
    )


@pytest.mark.asyncio
async def test_recover_injects_hint_and_agent_corrects() -> None:
    """The agent sees the hint on its second attempt and produces a passing output."""
    executor, writer = _executor_with_writer(max_recovery_attempts=2)
    run = await executor.run(dag=_dag())

    write_result = next(r for r in run.node_results if r.node_id == NodeID("write"))
    # The node ultimately succeeded after one recovery.
    assert write_result.success is True
    assert len(str(write_result.output)) >= 100
    assert write_result.metadata["recovery_attempts"] == 1
    # The writer ran twice: once short, once with a hint.
    assert writer.attempts == 2
    # The hint surfaced in agent_context.global_memory on attempt 2.
    assert any(h.get("code") == "length" for h in writer.last_hints)


@pytest.mark.asyncio
async def test_recovery_exhausted_downgrades_to_reject() -> None:
    """Once max_recovery_attempts is spent, RECOVER turns into REJECT (gate_rejected)."""

    class _StubbornWriter:
        attempts = 0

        @property
        def id(self) -> AgentID:
            return AgentID("Stubborn")

        @property
        def description(self) -> str:
            return "stubborn"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(self, goal: _DraftGoal, context: AgentContext) -> AgentResult[str]:
            type(self).attempts += 1
            return AgentResult.ok(output="nope", state=AgentState())

    registry = AgentRegistry()
    registry.register_agent(agent_instance=_StubbornWriter(), goal_type=_DraftGoal)
    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="write",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        )
    )
    node_executor = ContextNodeExecutor(
        agent_registry=registry, interceptor_pipeline=pipeline, max_recovery_attempts=1
    )

    node = Node.agent(id="write", name="write", agent_id="Stubborn")
    result = await node_executor.execute_node(node, Context())

    assert result.success is False
    block = result.metadata["interceptors"]
    assert block["recovery_exhausted"] is True
    assert block["gate_rejected"] is True
    assert block["recovery_attempts"] == 1
    # 1 initial attempt + 1 recovery = 2 runs.
    assert _StubbornWriter.attempts == 2


@pytest.mark.asyncio
async def test_recovery_disabled_treats_recover_as_reject() -> None:
    """max_recovery_attempts=0 means RECOVER never triggers a retry."""
    executor, writer = _executor_with_writer(max_recovery_attempts=0)
    run = await executor.run(dag=_dag())

    write_result = next(r for r in run.node_results if r.node_id == NodeID("write"))
    assert write_result.success is False
    assert write_result.metadata["interceptors"]["gate_rejected"] is True
    # Agent ran exactly once — no retry happened.
    assert writer.attempts == 1


@pytest.mark.asyncio
async def test_recovery_hint_trail_survives_agent_exception() -> None:
    """If the agent crashes mid-recovery, prior hints are preserved in metadata.

    Without this, ops would lose the diagnostic trail of which hints had been
    tried before the crash. The crash branch must stamp ``recovery_attempts``
    + ``recovery_hints_trail`` like the normal-completion branch does.
    """

    class _CrashingWriter:
        attempts = 0

        @property
        def id(self) -> AgentID:
            return AgentID("Crasher")

        @property
        def description(self) -> str:
            return "crasher"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(self, goal: _DraftGoal, context: AgentContext) -> AgentResult[str]:
            type(self).attempts += 1
            # Attempt 1: short → triggers RECOVER.  Attempt 2: explode.
            if type(self).attempts == 1:
                return AgentResult.ok(output="short", state=AgentState())
            raise RuntimeError("agent blew up on recovery attempt")

    registry = AgentRegistry()
    registry.register_agent(agent_instance=_CrashingWriter(), goal_type=_DraftGoal)
    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="write",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        )
    )
    node_executor = ContextNodeExecutor(
        agent_registry=registry, interceptor_pipeline=pipeline, max_recovery_attempts=2
    )
    node = Node.agent(id="write", name="write", agent_id="Crasher")
    result = await node_executor.execute_node(node, Context())

    assert result.success is False
    assert result.error is not None
    assert "blew up" in result.error
    # The trail from attempt 1's RECOVER decision is preserved.
    assert result.metadata["recovery_attempts"] == 1
    trail = result.metadata["recovery_hints_trail"]
    assert isinstance(trail, list) and len(trail) == 1
    assert trail[0]["code"] == "length"


@pytest.mark.asyncio
async def test_bootstrap_create_executor_threads_max_recovery_attempts() -> None:
    """The canonical entry point ``create_executor`` must wire the recovery budget.

    Without this, RuntimeServices.max_recovery_attempts is a dead-end seam — the
    primitive exists but no one going through bootstrap can configure it. This
    test proves the field actually flows from the services bundle into the
    ContextNodeExecutor that the bootstrap composition root builds.
    """
    writer = _LearningWriter()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=writer, goal_type=_DraftGoal)

    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="write",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        )
    )
    services = RuntimeServices(
        interceptor_pipeline=pipeline,
        max_recovery_attempts=2,
    )
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=services,
    )
    run = await executor.run(dag=_dag())

    write_result = next(r for r in run.node_results if r.node_id == NodeID("write"))
    # Bootstrap-built executor honoured the recovery budget end-to-end:
    # attempt 1 was short → RECOVER; attempt 2 saw the hint → produced ≥100 chars.
    assert write_result.success is True
    assert write_result.metadata["recovery_attempts"] == 1
    assert writer.attempts == 2


@pytest.mark.asyncio
async def test_reject_path_unchanged_when_on_failure_is_default() -> None:
    """GateEvalInterceptor with default on_failure=REJECT keeps the existing semantics."""
    writer = _LearningWriter()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=writer, goal_type=_DraftGoal)
    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="write",
                threshold=0.5,
                # default: REJECT
            ),
        )
    )
    node_executor = ContextNodeExecutor(agent_registry=registry, interceptor_pipeline=pipeline)
    services = RuntimeServices(interceptor_pipeline=pipeline)
    executor = DAGExecutor(
        node_executor=node_executor,
        services=services,
        config=ExecutorConfig(enable_events=False),
    )
    run = await executor.run(dag=_dag())

    result = next(r for r in run.node_results if r.node_id == NodeID("write"))
    assert result.success is False
    # No retry — REJECT mode is unchanged.
    assert writer.attempts == 1
