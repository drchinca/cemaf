"""Integration test: AgentCouncil through the real ContextNodeExecutor (SPEC-10).

Real CouncilMember agents registered in a real AgentRegistry; a real council Node
runs through the real executor with a real DefaultVoteAggregator. Proves the
council deliberates, the vote decides, the winning choice becomes NodeResult.output
(steering the DAG), and full ballot provenance lands on metadata. No mocks.
"""

from __future__ import annotations

import pytest

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.context.context import Context
from cemaf.core.types import AgentID
from cemaf.council.types import Opinion
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import Node


class _VotingMember:
    """A real council member — a full Agent that ALSO knows how to deliberate."""

    def __init__(self, member_id: str, choice: str) -> None:
        self._id = AgentID(member_id)
        self._choice = choice

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"votes {self._choice}"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: object, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._choice, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
        return Opinion(member_id=self._id, choice=self._choice)


def _registry(*members: tuple[str, str]) -> AgentRegistry:
    reg = AgentRegistry()
    for name, choice in members:
        reg.register_instance(item=_VotingMember(name, choice))
    return reg


@pytest.mark.asyncio
async def test_council_node_decides_and_steers_dag() -> None:
    registry = _registry(("v1", "approve"), ("v2", "approve"), ("v3", "reject"))
    executor = ContextNodeExecutor(agent_registry=registry)
    node = Node.council(
        id="gate",
        name="ship gate",
        members=("v1", "v2", "v3"),
        options=("approve", "reject"),
        prompt="ship it?",
        output_key="verdict",
    )

    result = await executor.execute_node(node, Context())

    assert result.success
    assert result.output == "approve"  # 2-1 majority — becomes node output (steers DAG)
    council = result.metadata["council"]
    assert council["winning_choice"] == "approve"
    assert council["tally"] == {"approve": 2.0, "reject": 1.0}
    assert len(council["ballots"]) == 3


@pytest.mark.asyncio
async def test_council_no_decision_is_success_empty_output() -> None:
    """Unanimous method with dissent → no verdict → success + empty output, not failure."""
    registry = _registry(("v1", "approve"), ("v2", "reject"))
    executor = ContextNodeExecutor(agent_registry=registry)
    node = Node.council(
        id="gate",
        name="ship gate",
        members=("v1", "v2"),
        options=("approve", "reject"),
        method="unanimous",
        output_key="verdict",
    )

    result = await executor.execute_node(node, Context())

    assert result.success  # legitimate non-verdict, NOT a crash
    assert result.output == ""
    assert result.metadata["council"]["winning_choice"] is None


@pytest.mark.asyncio
async def test_council_node_with_no_members_errors() -> None:
    registry = _registry()  # empty
    executor = ContextNodeExecutor(agent_registry=registry)
    node = Node.council(id="gate", name="g", members=("missing",), options=("a", "b"))

    result = await executor.execute_node(node, Context())

    assert not result.success
    assert "CouncilMember" in (result.error or "")


@pytest.mark.asyncio
async def test_council_full_dag_run_routes_on_verdict() -> None:
    """End-to-end through DAGExecutor: a council verdict is readable downstream."""
    from cemaf.bootstrap import create_executor
    from cemaf.core.types import NodeID
    from cemaf.orchestration.dag import DAG

    registry = _registry(("v1", "approve"), ("v2", "approve"))
    council_node = Node.council(
        id="gate",
        name="gate",
        members=("v1", "v2"),
        options=("approve", "reject"),
        output_key="verdict",
    )
    dag = DAG(
        name="council-dag",
        nodes=(council_node,),
        edges=(),
        entry_node=NodeID("gate"),
    )
    executor = create_executor(agent_registry=registry)

    run = await executor.run(dag=dag)

    assert run is not None
    gate_result = next(r for r in run.node_results if r.node_id == NodeID("gate"))
    assert gate_result.success
    assert gate_result.output == "approve"
