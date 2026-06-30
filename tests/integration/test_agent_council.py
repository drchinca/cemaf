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
async def test_council_node_rounds_propagates_through_resolver() -> None:
    """``Node.council(rounds=N)`` must reach ``CouncilConfig.rounds`` end-to-end.

    Without this, multi-round deliberation is reachable only by hand-building
    AgentCouncil outside the DAG — a dead-end seam. This proves the DAG-facing
    API exposes the primitive: a swing voter that revises in round 2 actually
    flips the verdict because the resolver honours rounds=2.
    """
    from cemaf.interceptors.types import COUNCIL_PRIOR_ROUND_KEY

    class _Swing:
        def __init__(self) -> None:
            self._id = AgentID("swing")
            self._calls = 0

        @property
        def id(self) -> AgentID:
            return self._id

        @property
        def description(self) -> str:
            return "swing voter"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(self, goal: object, context: AgentContext) -> AgentResult[str]:
            return AgentResult.ok(output="ship", state=AgentState())

        async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
            self._calls += 1
            # Round 1: vote with the apparent majority. Round 2: see the
            # broadcast, decide they're outvoting a holdout, switch.
            if self._calls == 1:
                return Opinion(member_id=self._id, choice="ship")
            prior = context.global_memory.get(COUNCIL_PRIOR_ROUND_KEY, [])
            assert isinstance(prior, list) and len(prior) == 3, "rounds=2 must broadcast"
            return Opinion(member_id=self._id, choice="hold")

    registry = AgentRegistry()
    registry.register_instance(item=_VotingMember("ship_voter", "ship"))
    registry.register_instance(item=_VotingMember("holder", "hold"))
    registry.register_instance(item=_Swing())
    executor = ContextNodeExecutor(agent_registry=registry)

    node = Node.council(
        id="gate",
        name="ship gate",
        members=("ship_voter", "holder", "swing"),
        options=("ship", "hold"),
        rounds=2,
        output_key="verdict",
    )
    result = await executor.execute_node(node, Context())

    # Round 1: 2-1 ship. Round 2: swing flips → 2-1 hold.
    assert result.success
    assert result.output == "hold"
    assert result.metadata["council"]["tally"] == {"ship": 1.0, "hold": 2.0}


def test_council_node_rejects_rounds_less_than_one() -> None:
    """The factory must validate rounds at the call site, not silently fall back."""
    with pytest.raises(ValueError, match="rounds must be >= 1"):
        Node.council(id="gate", name="g", members=("a",), options=("x", "y"), rounds=0)


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
async def test_council_full_dag_run_records_verdict() -> None:
    """End-to-end through DAGExecutor: the council node runs and outputs its verdict."""
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
    dag = DAG(name="council-dag", nodes=(council_node,), edges=(), entry_node=NodeID("gate"))
    executor = create_executor(agent_registry=registry)

    run = await executor.run(dag=dag)

    assert run is not None
    gate_result = next(r for r in run.node_results if r.node_id == NodeID("gate"))
    assert gate_result.success
    assert gate_result.output == "approve"


@pytest.mark.asyncio
async def test_council_verdict_steers_downstream_edge() -> None:
    """The council verdict, written to output_key, gates a downstream node via JSON_RULE.

    Proves the 'steers the DAG' claim: a gated node runs ONLY because the council
    decided 'approve' and an edge condition reads $$verdict$$ == 'approve'.
    """
    from pydantic import BaseModel

    from cemaf.agents.base import AgentResult, AgentState
    from cemaf.bootstrap import create_executor
    from cemaf.core.types import NodeID
    from cemaf.orchestration.dag import DAG, Condition, ConditionOperator, Edge, EdgeCondition

    ran: list[str] = []

    class _ShipGoal(BaseModel):
        pass

    class _Shipper:
        @property
        def id(self) -> AgentID:
            return AgentID("Shipper")

        @property
        def description(self) -> str:
            return "ships when approved"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(self, goal: _ShipGoal, context: AgentContext) -> AgentResult[str]:
            ran.append("Shipper")
            return AgentResult.ok(output="shipped", state=AgentState())

    registry = _registry(("v1", "approve"), ("v2", "approve"))
    registry.register_agent(agent_instance=_Shipper(), goal_type=_ShipGoal)

    gate = Node.council(
        id="gate",
        name="gate",
        members=("v1", "v2"),
        options=("approve", "reject"),
        output_key="verdict",
    )
    ship = Node.agent(id="ship", name="ship", agent_id="Shipper", output_key="ship_out")
    dag = DAG(
        name="gated-ship",
        nodes=(gate, ship),
        edges=(
            Edge(
                source=NodeID("gate"),
                target=NodeID("ship"),
                condition=EdgeCondition.JSON_RULE,
                condition_rule=Condition(field="verdict", operator=ConditionOperator.EQUALS, value="approve"),
            ),
        ),
        entry_node=NodeID("gate"),
    )
    executor = create_executor(agent_registry=registry)

    run = await executor.run(dag=dag)

    assert run is not None
    # The downstream Shipper ran ONLY because the council verdict opened the edge.
    assert ran == ["Shipper"]
    ship_result = next((r for r in run.node_results if r.node_id == NodeID("ship")), None)
    assert ship_result is not None and ship_result.output == "shipped"


@pytest.mark.asyncio
async def test_council_iterative_remediation_loop() -> None:
    """End-to-end integration:

    1. A loop runs a Developer agent and an Auditor Council.
    2. On iteration 1, the developer generates raw 'Draft Code'.
    3. The Council deliberates, sees 'Draft Code', and rejects it (veto).
    4. On iteration 2, the developer reads the previous council verdict of 'reject',
       and refactors the code to 'Polished Code'.
    5. The Council deliberates again, sees 'Polished Code', and approves it.
    6. The loop exit condition ('is_approved') is met, and the loop gracefully terminates.
    """
    from pydantic import BaseModel

    from cemaf.agents.base import Agent, AgentResult, AgentState
    from cemaf.agents.registry import AgentRegistry
    from cemaf.bootstrap import create_executor
    from cemaf.core.enums import RunStatus
    from cemaf.core.types import AgentID, NodeID
    from cemaf.council.protocols import Opinion
    from cemaf.orchestration.dag import DAG

    class _DeveloperGoal(BaseModel):
        verdict: str = ""

    class _DeveloperAgent(Agent[_DeveloperGoal, str]):
        def __init__(self) -> None:
            self.iterations = 0

        @property
        def id(self) -> AgentID:
            return AgentID("Developer")

        @property
        def description(self) -> str:
            return "generates and refactors code"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(self, goal: _DeveloperGoal, context: AgentContext) -> AgentResult[str]:
            self.iterations += 1
            if goal.verdict == "reject":
                return AgentResult.ok(output="Polished Code", state=AgentState())
            return AgentResult.ok(output="Draft Code", state=AgentState())

    class _AuditorAgent(Agent[object, str]):
        def __init__(self, name: str) -> None:
            self._id = AgentID(name)

        @property
        def id(self) -> AgentID:
            return self._id

        @property
        def description(self) -> str:
            return f"auditor {self._id}"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(self, goal: object, context: AgentContext) -> AgentResult[str]:
            return AgentResult.ok(output="reject", state=AgentState())

        async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
            # Look at code inside goal (which contains the node's resolved inputs)
            code = ""
            if isinstance(goal, dict):
                code = goal.get("code")
            if code == "Polished Code":
                return Opinion(member_id=self._id, choice="approve")
            return Opinion(member_id=self._id, choice="reject")

    class _CheckGoal(BaseModel):
        verdict: str = ""

    class _CheckAgent(Agent[_CheckGoal, str]):
        @property
        def id(self) -> AgentID:
            return AgentID("CheckAgent")

        @property
        def description(self) -> str:
            return "converts verdict to boolean"

        @property
        def skills(self) -> tuple[()]:
            return ()

        async def run(self, goal: _CheckGoal, context: AgentContext) -> AgentResult[str]:
            output = "approved" if (goal.verdict == "approve") else ""
            return AgentResult.ok(output=output, state=AgentState())

    # Setup Agent Registry with candidates
    dev_agent = _DeveloperAgent()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=dev_agent, goal_type=_DeveloperGoal)
    registry.register_instance(item=_AuditorAgent("v1"))
    registry.register_instance(item=_AuditorAgent("v2"))
    registry.register_agent(agent_instance=_CheckAgent(), goal_type=_CheckGoal)

    # Construct the DAG
    loop_node = Node.loop(
        id="loop",
        name="review_loop",
        body_node_ids=("developer", "gate", "check"),
        max_iterations=5,
        exit_condition="is_approved",
    )
    developer_node = Node.agent(
        id="developer",
        name="developer",
        agent_id="Developer",
        input_mapping={"verdict": "$$verdict$$"},
        output_key="code",
    )
    gate_node = Node.council(
        id="gate",
        name="gate",
        members=("v1", "v2"),
        options=("approve", "reject"),
        input_mapping={"code": "$$code$$"},
        output_key="verdict",
    )
    check_node = Node.agent(
        id="check",
        name="check",
        agent_id="CheckAgent",
        input_mapping={"verdict": "$$verdict$$"},
        output_key="is_approved",
    )

    dag = DAG(
        name="iterative-council-remediation",
        nodes=(loop_node, developer_node, gate_node, check_node),
        edges=(),
        entry_node=NodeID("loop"),
    )

    executor = create_executor(agent_registry=registry)
    run = await executor.run(dag=dag)

    assert run is not None
    assert run.success is True
    assert run.status == RunStatus.COMPLETED

    # The loop should have executed exactly 2 iterations before exiting
    assert dev_agent.iterations == 2

    # The final context should carry the approved, polished code
    assert run.final_context.get("code") == "Polished Code"
    assert run.final_context.get("verdict") == "approve"
    assert run.final_context.get("is_approved") == "approved"
