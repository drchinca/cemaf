"""Contract tests for LOOP node type in DAG execution."""

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import NodeType
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult


class MockLoopNodeExecutor:
    """Mock executor that counts iterations via context."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        self.calls.append(str(node.id))
        # Increment iteration counter in context
        count = context.get("iteration_count", default=0)
        return NodeResult(
            node_id=node.id,
            success=True,
            output=str(count + 1),
            metadata={"iteration_count": count + 1},
        )


class TestLoopNodeType:
    """Contract: LOOP node type must exist and be usable in DAGs."""

    def test_loop_node_type_exists(self) -> None:
        """NodeType must include LOOP."""
        assert hasattr(NodeType, "LOOP")
        assert NodeType.LOOP.value == "loop"

    def test_create_loop_node(self) -> None:
        """Node.loop() factory must create a LOOP node with max_iterations and exit_condition."""
        node = Node.loop(
            id="loop-1",
            name="Refine Loop",
            body_node_ids=("refine-step",),
            max_iterations=5,
            exit_condition="quality_score > 0.9",
        )

        assert node.type == NodeType.LOOP
        assert node.id == "loop-1"
        assert node.config.get("max_iterations") == 5
        assert node.config.get("exit_condition") == "quality_score > 0.9"
        assert node.config.get("body_node_ids") == ["refine-step"]

    def test_loop_in_dag(self) -> None:
        """A LOOP node must be addable to a DAG."""
        dag = DAG(name="test-loop-dag")
        body_node = Node.agent(id="refine", name="Refine", agent_id="Refiner")
        loop_node = Node.loop(
            id="loop-1",
            name="Refine Loop",
            body_node_ids=("refine",),
            max_iterations=3,
        )
        dag = dag.add_node(node=body_node)
        dag = dag.add_node(node=loop_node)

        assert dag.get_node("loop-1") is not None
        assert dag.get_node("loop-1").type == NodeType.LOOP

    @pytest.mark.asyncio
    async def test_loop_executes_body_up_to_max_iterations(self) -> None:
        """LOOP node must execute body nodes up to max_iterations when exit_condition is not met."""
        executor_mock = MockLoopNodeExecutor()
        dag_executor = DAGExecutor(node_executor=executor_mock)

        body_node = Node.agent(id="step", name="Step", agent_id="Stepper", output_key="step_output")
        loop_node = Node.loop(
            id="loop-1",
            name="Loop",
            body_node_ids=("step",),
            max_iterations=3,
        )

        dag = DAG(name="loop-dag")
        dag = dag.add_node(node=body_node)
        dag = dag.add_node(node=loop_node)
        dag = dag.add_edge(edge=Edge(source="loop-1", target="step"))

        result = await dag_executor.run(dag=dag, initial_context=Context())

        # The body node "step" should be called 3 times (max_iterations)
        step_calls = [c for c in executor_mock.calls if c == "step"]
        assert len(step_calls) == 3
        assert result.status.value == "completed"
