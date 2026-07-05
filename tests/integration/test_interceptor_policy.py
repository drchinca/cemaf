"""Integration: PolicyInterceptor on the interceptor spine BLOCKS a real DAG.

A real 2-node DAG (gen → use, ON_SUCCESS) with a PolicyInterceptor on
`gen`: DENY → `use` never runs; ALLOW → `use` runs. Mirrors the shape of
`test_interceptor_gate.py` so the two seams share the same proof pattern
(pipeline is the spine, engines are pluggable decisions).

No mocks: real executor, real registry, real InterceptorPipeline. The
policy engine is a small in-test class satisfying the PolicyEngine
protocol — engines are BYO, so this test doubles as the reference shape.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.interceptors import (
    AllowAllEngine,
    PolicyDecision,
    PolicyEffect,
    PolicyInterceptor,
    create_interceptor_pipeline,
)
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _GenGoal(BaseModel):
    pass


class _Gen:
    def __init__(self) -> None:
        self.runs = 0

    @property
    def id(self) -> AgentID:
        return AgentID("gen")

    @property
    def description(self) -> str:
        return "generator"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _GenGoal, context: AgentContext) -> AgentResult[str]:
        self.runs += 1
        return AgentResult.ok(output="ok", state=AgentState())


class _UseGoal(BaseModel):
    pass


class _Use:
    def __init__(self, ran: list[str]) -> None:
        self._ran = ran

    @property
    def id(self) -> AgentID:
        return AgentID("use")

    @property
    def description(self) -> str:
        return "consumer"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _UseGoal, context: AgentContext) -> AgentResult[str]:
        self._ran.append("use")
        return AgentResult.ok(output="used", state=AgentState())


class _DenyOnPattern:
    """Engine that DENYs any node whose id matches a pattern; allows everything else."""

    def __init__(self, *, deny_node_id: str, reason: str, rule_id: str) -> None:
        self._deny = deny_node_id
        self._reason = reason
        self._rule = rule_id

    async def decide(self, *, node: Node, context: AgentContext) -> PolicyDecision:
        if str(node.id) == self._deny:
            return PolicyDecision(effect=PolicyEffect.DENY, reason=self._reason, rule_id=self._rule)
        return PolicyDecision(effect=PolicyEffect.ALLOW)


def _dag() -> DAG:
    gen = Node.agent(id="gen", name="gen", agent_id="gen", output_key="draft")
    use = Node.agent(id="use", name="use", agent_id="use", output_key="final")
    return DAG(
        name="policy_test",
        nodes=(gen, use),
        edges=(Edge(source=NodeID("gen"), target=NodeID("use"), condition=EdgeCondition.ON_SUCCESS),),
        entry_node=NodeID("gen"),
    )


def _registry(gen: _Gen, ran: list[str]) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_agent(agent_instance=gen, goal_type=_GenGoal)
    reg.register_agent(agent_instance=_Use(ran), goal_type=_UseGoal)
    return reg


@pytest.mark.asyncio
async def test_policy_deny_blocks_downstream_and_does_not_run_agent() -> None:
    gen, ran = _Gen(), []
    engine = _DenyOnPattern(
        deny_node_id="gen",
        reason="workspace boundary violation",
        rule_id="rule_ws_scoped",
    )
    executor = create_executor(
        agent_registry=_registry(gen, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(
            interceptor_pipeline=create_interceptor_pipeline(interceptors=(PolicyInterceptor(engine=engine),))
        ),
    )
    run = await executor.run(dag=_dag())

    gen_result = next(r for r in run.node_results if r.node_id == NodeID("gen"))
    # PRE-reject flips the node to failure — downstream never sees ON_SUCCESS.
    assert gen_result.success is False
    assert "policy denied" in (gen_result.error or "")
    assert gen.runs == 0, "agent must never run when policy denies"
    assert ran == [], "downstream must not execute after a PRE reject"


@pytest.mark.asyncio
async def test_policy_allow_lets_dag_complete() -> None:
    gen, ran = _Gen(), []
    executor = create_executor(
        agent_registry=_registry(gen, ran),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(
            interceptor_pipeline=create_interceptor_pipeline(
                interceptors=(PolicyInterceptor(engine=AllowAllEngine()),)
            )
        ),
    )
    run = await executor.run(dag=_dag())

    assert run.status is RunStatus.COMPLETED
    assert gen.runs == 1
    assert ran == ["use"]
