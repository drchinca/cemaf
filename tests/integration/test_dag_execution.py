"""
Integration test for DAG execution.

Tests the full DAG execution flow with mock nodes.

Uses fixtures from conftest.py:
- simple_dag: Linear DAG (A → B → C)
- diamond_dag: Diamond DAG (A → (B, C) → D)
- mock_node_executor: MockNodeExecutor with tracking
- dag_executor: DAGExecutor with mock node executor
"""

import pytest

from cemaf.context.context import Context  # New import
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Condition, ConditionOperator, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult

# Import MockNodeExecutor from conftest for type hints
from tests.conftest import MockNodeExecutor


class TestDAGExecution:
    """Integration tests for DAG execution."""

    @pytest.mark.asyncio
    async def test_simple_linear_dag(self, simple_dag: DAG, mock_node_executor: MockNodeExecutor):
        """Execute a simple linear DAG: A -> B -> C."""
        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(
            simple_dag, initial_context=Context(data={"initial": "data"})
        )  # Updated initial_context

        # Verify
        assert result.success
        assert len(result.node_results) == 3
        assert result.final_context.get("a_out") == "success_a"  # Updated assertion
        assert result.final_context.get("b_out") == "success_b"  # Updated assertion
        assert result.final_context.get("c_out") == "success_c"  # Updated assertion
        assert result.final_context.get("initial") == "data"  # Ensure initial context is preserved

    @pytest.mark.asyncio
    async def test_conditional_edge_on_success(self, mock_node_executor: MockNodeExecutor):
        """Edge with ON_SUCCESS only traverses on success."""
        dag = DAG(name="conditional")
        dag = dag.add_node(
            Node.tool(id="start", name="Start", tool_id="t1", output_key="start_out")
        )  # Added output_key
        dag = dag.add_node(
            Node.tool(id="success_path", name="Success", tool_id="t2", output_key="success_path_out")
        )  # Added output_key
        dag = dag.add_edge(
            Edge(
                source=NodeID("start"),
                target=NodeID("success_path"),
                condition=EdgeCondition.ON_SUCCESS,
            )
        )

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(dag)

        assert result.success
        assert "success_path" in mock_node_executor.executed
        assert result.final_context.get("start_out") == "success_start"
        assert result.final_context.get("success_path_out") == "success_success_path"

    @pytest.mark.asyncio
    async def test_execution_order(self, diamond_dag: DAG, mock_node_executor: MockNodeExecutor):
        """Nodes execute in topological order."""
        executor = DAGExecutor(node_executor=mock_node_executor)
        await executor.run(diamond_dag)

        # A must be first
        assert mock_node_executor.executed.index("a") == 0
        # D must be last
        assert mock_node_executor.executed.index("d") == 3
        # B and C must be between A and D
        assert mock_node_executor.executed.index("b") > 0
        assert mock_node_executor.executed.index("c") > 0
        assert mock_node_executor.executed.index("b") < 3
        assert mock_node_executor.executed.index("c") < 3

    @pytest.mark.asyncio
    async def test_failure_handling(self):
        """DAG handles node failures."""
        dag = DAG(name="with_failure")
        dag = dag.add_node(Node.tool(id="good", name="Good", tool_id="t", output_key="good"))
        # Create node manually to set retry_on_failure=False
        bad_node = Node(
            id=NodeID("bad"),
            type=NodeType.TOOL,
            name="Bad",
            ref_id="t",
            retry_on_failure=False,
        )
        dag = dag.add_node(bad_node)
        dag = dag.add_edge(Edge(source=NodeID("good"), target=NodeID("bad")))

        # Use node_results kwarg to configure specific node outcomes
        mock = MockNodeExecutor(
            node_results={"bad": NodeResult(node_id=NodeID("bad"), success=False, error="Failed!")}
        )
        executor = DAGExecutor(node_executor=mock)
        result = await executor.run(dag)

        assert not result.success
        assert result.error == "Failed!"

    @pytest.mark.asyncio
    async def test_context_propagation(self, mock_node_executor: MockNodeExecutor):
        """Context is passed and updated through nodes."""
        dag = DAG(name="context_test")
        dag = dag.add_node(Node.tool(id="n1", name="N1", tool_id="t", output_key="step1"))
        dag = dag.add_node(Node.tool(id="n2", name="N2", tool_id="t", output_key="step2"))
        dag = dag.add_edge(Edge(source=NodeID("n1"), target=NodeID("n2")))

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(
            dag, initial_context=Context(data={"initial_data": "hello"})
        )  # Updated initial_context

        # Initial data preserved
        assert result.final_context.get("initial_data") == "hello"  # Updated assertion
        # Node outputs added
        assert result.final_context.get("step1") == "success_n1"  # Updated assertion
        assert result.final_context.get("step2") == "success_n2"  # Updated assertion

    @pytest.mark.asyncio
    async def test_router_selects_route(self, mock_node_executor: MockNodeExecutor):
        """Router node selects a route and skips other branches."""
        dag = DAG(name="router_test")
        router = Node(
            id=NodeID("router"),
            type=NodeType.ROUTER,
            name="Router",
            routes={"success": "success", "failure": "failure"},
            config={"route_key": "route"},
            output_key="router_out",  # Added output_key to router
        )
        dag = dag.add_node(router)
        dag = dag.add_node(Node.tool(id="success", name="Success", tool_id="t"))
        dag = dag.add_node(Node.tool(id="failure", name="Failure", tool_id="t"))
        dag = dag.add_edge(Edge(source=NodeID("router"), target=NodeID("success")))
        dag = dag.add_edge(Edge(source=NodeID("router"), target=NodeID("failure")))

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(
            dag, initial_context=Context(data={"route": "success"})
        )  # Updated initial_context

        assert result.success
        assert "success" in mock_node_executor.executed
        assert "failure" not in mock_node_executor.executed
        assert result.final_context.get("router_out") == ("success",)  # Verify router output

    @pytest.mark.asyncio
    async def test_conditional_node_branches(self, mock_node_executor: MockNodeExecutor):
        """Conditional node uses ON_SUCCESS/ON_FAILURE edges."""
        dag = DAG(name="conditional_test")
        cond = Node(
            id=NodeID("cond"),
            type=NodeType.CONDITIONAL,
            name="Condition",
            config={"condition_key": "ok"},
            output_key="cond_result",  # Added output_key to conditional node
        )
        dag = dag.add_node(cond)
        dag = dag.add_node(Node.tool(id="yes", name="Yes", tool_id="t"))
        dag = dag.add_node(Node.tool(id="no", name="No", tool_id="t"))
        dag = dag.add_edge(
            Edge(
                source=NodeID("cond"),
                target=NodeID("yes"),
                condition=EdgeCondition.ON_SUCCESS,
            )
        )
        dag = dag.add_edge(
            Edge(
                source=NodeID("cond"),
                target=NodeID("no"),
                condition=EdgeCondition.ON_FAILURE,
            )
        )

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(
            dag, initial_context=Context(data={"ok": True})
        )  # Updated initial_context

        assert result.success
        assert "yes" in mock_node_executor.executed
        assert "no" not in mock_node_executor.executed
        assert result.final_context.get("cond_result") is True  # Verify conditional node output

    @pytest.mark.asyncio
    async def test_conditional_node_routes_with_rule(self, mock_node_executor: MockNodeExecutor):
        """Conditional node routes using a Condition rule and routes mapping."""
        condition_rule = Condition(
            field="proceed",
            operator=ConditionOperator.EQUALS,
            value=True,
        )
        dag = DAG(name="conditional_route_test")
        cond_node = Node.conditional(
            id="cond",
            name="Should proceed?",
            condition=condition_rule,
            routes={True: "yes", False: "no"},
            output_key="cond_output",
        )
        dag = dag.add_node(cond_node)
        dag = dag.add_node(Node.tool(id="yes", name="Yes path", tool_id="t", output_key="yes_out"))
        dag = dag.add_node(Node.tool(id="no", name="No path", tool_id="t", output_key="no_out"))
        # Edges are ALWAYS; routing is controlled via _route_choices from the conditional node
        dag = dag.add_edge(Edge(source=NodeID("cond"), target=NodeID("yes")))
        dag = dag.add_edge(Edge(source=NodeID("cond"), target=NodeID("no")))

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(dag, initial_context=Context(data={"proceed": True}))

        assert result.success
        assert "yes" in mock_node_executor.executed
        assert "no" not in mock_node_executor.executed
        assert result.final_context.get("cond_output") is True
        assert result.final_context.get("yes_out") == "success_yes"

    @pytest.mark.asyncio
    async def test_join_any_allows_partial(self, mock_node_executor: MockNodeExecutor):
        """Join=any allows execution when only one incoming edge is satisfied."""
        dag = DAG(name="join_any")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t", output_key="a_out"))  # Added output_key
        dag = dag.add_node(Node.tool(id="b", name="B", tool_id="t", output_key="b_out"))  # Added output_key
        dag = dag.add_node(
            Node(
                id=NodeID("c"),
                type=NodeType.TOOL,
                name="C",
                ref_id="t",
                config={"join": "any"},
                output_key="c_out",  # Added output_key
            )
        )
        dag = dag.add_edge(
            Edge(
                source=NodeID("a"),
                target=NodeID("b"),
                condition=EdgeCondition.ON_FAILURE,
            )
        )
        dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("c")))
        dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("c")))

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(dag)

        assert result.success
        assert "c" in mock_node_executor.executed
        assert result.final_context.get("c_out") == "success_c"  # Verify output

    @pytest.mark.asyncio
    async def test_parallel_node_executes_children_once(self, mock_node_executor: MockNodeExecutor):
        """Parallel node executes its child nodes and avoids duplicate runs."""
        dag = DAG(name="parallel_test")
        dag = dag.add_node(
            Node.parallel(
                id="parallel",
                name="Parallel",
                parallel_nodes=["a", "b"],
                output_key="parallel_results",  # Added output_key
            )
        )
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t", output_key="a_res"))  # Added output_key
        dag = dag.add_node(Node.tool(id="b", name="B", tool_id="t", output_key="b_res"))  # Added output_key
        dag = dag.add_node(Node.tool(id="c", name="C", tool_id="t", output_key="c_res"))  # Added output_key
        dag = dag.add_edge(Edge(source=NodeID("parallel"), target=NodeID("a")))
        dag = dag.add_edge(Edge(source=NodeID("parallel"), target=NodeID("b")))
        dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("c")))
        dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("c")))

        executor = DAGExecutor(node_executor=mock_node_executor)
        initial_context = Context(data={"some_key": "some_value"})
        result = await executor.run(dag, initial_context=initial_context)

        assert result.success
        assert mock_node_executor.executed.count("a") == 1
        assert mock_node_executor.executed.count("b") == 1
        assert "c" in mock_node_executor.executed

        assert result.final_context.get("some_key") == "some_value"  # Ensure initial context preserved
        assert result.final_context.get("a_res") == "success_a"
        assert result.final_context.get("b_res") == "success_b"
        assert result.final_context.get("c_res") == "success_c"
        assert result.final_context.get("parallel_results") == {"a": "success_a", "b": "success_b"}

    @pytest.mark.asyncio
    async def test_hierarchical_context_and_merging(self, mock_node_executor: MockNodeExecutor):
        """
        Tests that parallel branches receive a derived context and their changes are merged.
        Parent context should remain immutable for branches not merging back.
        """
        dag = DAG(name="hierarchical_context")
        dag = dag.add_node(Node.tool(id="start", name="Start", tool_id="t", output_key="start_data"))
        dag = dag.add_node(
            Node.parallel(
                id="parallel_branch",
                name="Parallel Branch",
                parallel_nodes=["child1", "child2"],
                output_key="parallel_output",
            )
        )
        dag = dag.add_node(Node.tool(id="child1", name="Child 1", tool_id="t", output_key="child1_data"))
        dag = dag.add_node(Node.tool(id="child2", name="Child 2", tool_id="t", output_key="child2_data"))
        dag = dag.add_node(Node.tool(id="end", name="End", tool_id="t", output_key="end_data"))

        dag = dag.add_edge(Edge(source=NodeID("start"), target=NodeID("parallel_branch")))
        dag = dag.add_edge(Edge(source=NodeID("parallel_branch"), target=NodeID("end")))

        # Define specific results for children to show context manipulation
        mock_node_executor.node_results = {
            "start": NodeResult(node_id="start", success=True, output={"initial": "value"}),
            "child1": NodeResult(node_id="child1", success=True, output="child1_new_val"),
            "child2": NodeResult(node_id="child2", success=True, output="child2_new_val"),
            "end": NodeResult(node_id="end", success=True, output="final_processing"),
        }

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(dag, initial_context=Context(data={"global_key": "global_value"}))

        assert result.success

        # Verify initial context is preserved
        assert result.final_context.get("global_key") == "global_value"

        # Verify start node output
        assert result.final_context.get("start_data") == {"initial": "value"}

        # Verify parallel child outputs are merged
        assert result.final_context.get("child1_data") == "child1_new_val"
        assert result.final_context.get("child2_data") == "child2_new_val"

        # Verify parallel node's aggregated output
        assert result.final_context.get("parallel_output") == {
            "child1": "child1_new_val",
            "child2": "child2_new_val",
        }

        # Verify end node output
        assert result.final_context.get("end_data") == "final_processing"

    @pytest.mark.asyncio
    async def test_router_node_emits_patches(self, mock_node_executor: MockNodeExecutor):
        """Router nodes should emit context patches with correlation IDs."""
        from cemaf.observability.run_logger import InMemoryRunLogger

        run_logger = InMemoryRunLogger()
        dag = DAG(name="router_patch_test")

        # Add router node with output_key
        router_node = Node.router(
            id="router",
            name="Route selector",
            routes={"path_a": "target_a", "path_b": "target_b"},
        )
        # Update router to have output_key and config
        router_node = Node(
            id=NodeID("router"),
            type=NodeType.ROUTER,
            name="Route selector",
            routes={"path_a": "target_a", "path_b": "target_b"},
            config={"route_key": "selected_route"},
            output_key="router_output",
        )

        dag = dag.add_node(router_node)
        dag = dag.add_node(Node.tool(id="target_a", name="Target A", tool_id="t", output_key="a_out"))
        dag = dag.add_edge(Edge(source=NodeID("router"), target=NodeID("target_a")))

        executor = DAGExecutor(node_executor=mock_node_executor, run_logger=run_logger)
        result = await executor.run(dag, initial_context=Context(data={"selected_route": "path_a"}))

        assert result.success

        # Verify patches were recorded
        record = run_logger.get_current_record() or run_logger._history[-1]
        assert len(record.patches) > 0

        # Find router patch
        router_patches = [p for p in record.patches if p.source_id == "router"]
        assert len(router_patches) > 0
        assert router_patches[0].correlation_id  # Should have correlation ID

    @pytest.mark.asyncio
    async def test_conditional_node_emits_patches(self, mock_node_executor: MockNodeExecutor):
        """Conditional nodes should emit context patches with correlation IDs."""
        from cemaf.observability.run_logger import InMemoryRunLogger

        run_logger = InMemoryRunLogger()
        dag = DAG(name="conditional_patch_test")

        cond_node = Node.conditional(
            id="cond",
            name="Check condition",
            condition="proceed",
            routes={True: "yes", False: "no"},
            output_key="cond_result",
        )

        dag = dag.add_node(cond_node)
        dag = dag.add_node(Node.tool(id="yes", name="Yes path", tool_id="t", output_key="yes_out"))
        dag = dag.add_edge(Edge(source=NodeID("cond"), target=NodeID("yes")))

        executor = DAGExecutor(node_executor=mock_node_executor, run_logger=run_logger)
        result = await executor.run(dag, initial_context=Context(data={"proceed": True}))

        assert result.success

        # Verify patches were recorded
        record = run_logger.get_current_record() or run_logger._history[-1]
        assert len(record.patches) > 0

        # Find conditional patch
        cond_patches = [p for p in record.patches if p.source_id == "cond"]
        assert len(cond_patches) > 0
        assert cond_patches[0].correlation_id  # Should have correlation ID
        assert cond_patches[0].path == "cond_result"

    @pytest.mark.asyncio
    async def test_parallel_node_emits_patches(self, mock_node_executor: MockNodeExecutor):
        """Parallel nodes should emit context patches with correlation IDs."""
        from cemaf.observability.run_logger import InMemoryRunLogger

        run_logger = InMemoryRunLogger()
        dag = DAG(name="parallel_patch_test")

        parallel_node = Node.parallel(
            id="parallel",
            name="Run parallel",
            parallel_nodes=["child1", "child2"],
            output_key="parallel_output",
        )

        dag = dag.add_node(parallel_node)
        dag = dag.add_node(Node.tool(id="child1", name="Child 1", tool_id="t", output_key="c1_out"))
        dag = dag.add_node(Node.tool(id="child2", name="Child 2", tool_id="t", output_key="c2_out"))

        executor = DAGExecutor(node_executor=mock_node_executor, run_logger=run_logger)
        result = await executor.run(dag, initial_context=Context(data={}))

        assert result.success

        # Verify patches were recorded
        record = run_logger.get_current_record() or run_logger._history[-1]
        assert len(record.patches) > 0

        # Find parallel node patch
        parallel_patches = [p for p in record.patches if p.source_id == "parallel"]
        assert len(parallel_patches) > 0
        assert parallel_patches[0].correlation_id  # Should have correlation ID
        assert parallel_patches[0].path == "parallel_output"
