"""
Unit tests for the DAG module.

Tests:
- DAG creation and validation
- Node types
- Edge conditions
- Topological sort
- Cycle detection

Uses fixtures from conftest.py for reusable test data.
"""

import pytest

from cemaf.context.context import Context  # New import
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Condition, ConditionOperator, Edge, EdgeCondition, Node

# Fixtures used: simple_dag, diamond_dag (from conftest.py)


class TestNode:
    """Tests for Node."""

    def test_tool_node_creation(self):
        """Node.tool creates a tool node."""
        node = Node.tool(
            id="fetch",
            name="Fetch Data",
            tool_id="http_request",
            description="Fetches data from API",
        )

        assert node.id == "fetch"
        assert node.type == NodeType.TOOL
        assert node.ref_id == "http_request"

    def test_skill_node_creation(self):
        """Node.skill creates a skill node."""
        node = Node.skill(
            id="analyze",
            name="Analyze Data",
            skill_id="data_analysis",
        )

        assert node.type == NodeType.SKILL
        assert node.ref_id == "data_analysis"

    def test_agent_node_creation(self):
        """Node.agent creates an agent node."""
        node = Node.agent(
            id="writer",
            name="Content Writer",
            agent_id="writer_agent",
            config={"max_tokens": 1000},
        )

        assert node.type == NodeType.AGENT
        assert node.config["max_tokens"] == 1000

    def test_router_node_creation(self):
        """Node.router creates a router node."""
        node = Node.router(
            id="route",
            name="Route Decision",
            routes={"success": "next_node", "failure": "error_handler"},
        )

        assert node.type == NodeType.ROUTER
        assert node.routes["success"] == "next_node"

    def test_parallel_node_creation(self):
        """Node.parallel creates a parallel node."""
        node = Node.parallel(
            id="parallel",
            name="Run in Parallel",
            parallel_nodes=["task1", "task2", "task3"],
        )

        assert node.type == NodeType.PARALLEL
        assert len(node.parallel_nodes) == 3

    def test_conditional_node_creation_with_key(self):
        """Node.conditional configures condition_key and routes."""
        node = Node.conditional(
            id="cond1",
            name="Check flag",
            condition="flag",
            routes={True: "yes", False: "no"},
            output_key="cond_result",
        )

        assert node.type == NodeType.CONDITIONAL
        assert node.config["condition_key"] == "flag"
        assert node.routes[True] == "yes"
        assert node.output_key == "cond_result"

    def test_conditional_node_creation_with_rule(self):
        """Node.conditional accepts Condition objects."""
        rule = Condition(field="status", operator=ConditionOperator.EQUALS, value="ready")
        node = Node.conditional(
            id="cond2",
            name="Check status",
            condition=rule,
        )

        assert node.config["condition_rule"] == rule


class TestCondition:
    """Tests for the serializable Condition class."""

    @pytest.mark.parametrize(
        "field, op, value, context_dict, expected",
        [  # Changed 'context' to 'context_dict'
            # EQUALS
            ("count", ConditionOperator.EQUALS, 5, {"count": 5}, True),
            ("count", ConditionOperator.EQUALS, 5, {"count": 6}, False),
            # NOT_EQUALS
            ("status", ConditionOperator.NOT_EQUALS, "done", {"status": "pending"}, True),
            ("status", ConditionOperator.NOT_EQUALS, "done", {"status": "done"}, False),
            # GREATER_THAN
            ("score", ConditionOperator.GREATER_THAN, 80, {"score": 95}, True),
            ("score", ConditionOperator.GREATER_THAN, 80, {"score": 75}, False),
            ("score", ConditionOperator.GREATER_THAN, 80, {"score": None}, False),  # Test with None
            ("score", ConditionOperator.GREATER_THAN, None, {"score": 95}, False),  # Test with None
            # LESS_THAN
            ("retries", ConditionOperator.LESS_THAN, 3, {"retries": 1}, True),
            ("retries", ConditionOperator.LESS_THAN, 3, {"retries": 3}, False),
            ("retries", ConditionOperator.LESS_THAN, 3, {"retries": None}, False),  # Test with None
            ("retries", ConditionOperator.LESS_THAN, None, {"retries": 1}, False),  # Test with None
            # CONTAINS
            ("tags", ConditionOperator.CONTAINS, "urgent", {"tags": ["urgent", "review"]}, True),
            ("tags", ConditionOperator.CONTAINS, "urgent", {"tags": ["review"]}, False),
            ("message", ConditionOperator.CONTAINS, "error", {"message": "An error occurred"}, True),
            # IS_NONE
            ("result", ConditionOperator.IS_NONE, None, {"result": None}, True),
            ("result", ConditionOperator.IS_NONE, None, {"result": "value"}, False),
            # IS_NOT_NONE
            ("result", ConditionOperator.IS_NOT_NONE, None, {"result": "value"}, True),
            ("result", ConditionOperator.IS_NOT_NONE, None, {"result": None}, False),
            # Nested field
            ("data.user.id", ConditionOperator.EQUALS, 123, {"data": {"user": {"id": 123}}}, True),
            ("data.user.id", ConditionOperator.EQUALS, 123, {"data": {"user": {"id": 456}}}, False),
            # Field not found
            ("non_existent.field", ConditionOperator.EQUALS, 1, {}, False),
        ],
    )
    def test_condition_evaluation(self, field, op, value, context_dict, expected):
        """Condition evaluates correctly for all operators."""
        condition = Condition(field=field, operator=op, value=value)
        context = Context(data=context_dict)  # Pass Context object
        assert condition.evaluate(context) == expected


class TestEdge:
    """Tests for Edge."""

    def test_edge_creation(self):
        """Edge can be created with source and target."""
        edge = Edge(
            source=NodeID("node1"),
            target=NodeID("node2"),
        )

        assert edge.source == "node1"
        assert edge.target == "node2"
        assert edge.condition == EdgeCondition.ALWAYS

    def test_edge_with_condition(self):
        """Edge can have legacy conditions."""
        edge = Edge(
            source=NodeID("node1"),
            target=NodeID("node2"),
            condition=EdgeCondition.ON_SUCCESS,
        )

        assert edge.condition == EdgeCondition.ON_SUCCESS

    def test_should_traverse_always(self):
        """ALWAYS condition always returns True."""
        edge = Edge(
            source=NodeID("a"),
            target=NodeID("b"),
            condition=EdgeCondition.ALWAYS,
        )

        assert edge.should_traverse(Context()) is True  # Pass Context object

    def test_should_traverse_json_rule(self):
        """JSON_RULE condition uses the Condition object."""
        rule = Condition(field="proceed", operator=ConditionOperator.EQUALS, value=True)
        edge = Edge(
            source=NodeID("a"),
            target=NodeID("b"),
            condition=EdgeCondition.JSON_RULE,
            condition_rule=rule,
        )

        assert edge.should_traverse(Context(data={"proceed": True})) is True  # Pass Context object
        assert edge.should_traverse(Context(data={"proceed": False})) is False  # Pass Context object


class TestDAG:
    """Tests for DAG."""

    def test_dag_creation(self):
        """DAG can be created with name."""
        dag = DAG(name="test_pipeline")

        assert dag.name == "test_pipeline"
        assert len(dag.nodes) == 0
        assert len(dag.edges) == 0

    def test_add_node(self):
        """Nodes can be added to DAG."""
        dag = DAG(name="test")
        node = Node.tool(id="t1", name="Tool 1", tool_id="tool_1")

        dag = dag.add_node(node)

        assert len(dag.nodes) == 1
        assert dag.entry_node == "t1"

    def test_add_node_duplicate_raises(self):
        """Adding duplicate node raises error."""
        dag = DAG(name="test")
        node = Node.tool(id="t1", name="Tool 1", tool_id="tool_1")
        dag = dag.add_node(node)

        with pytest.raises(ValueError, match="already exists"):
            dag.add_node(node)

    def test_add_edge(self):
        """Edges can be added between nodes."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="t1", name="T1", tool_id="t1"))
        dag = dag.add_node(Node.tool(id="t2", name="T2", tool_id="t2"))

        dag = dag.add_edge(Edge(source=NodeID("t1"), target=NodeID("t2")))

        assert len(dag.edges) == 1

    def test_add_edge_invalid_source_raises(self):
        """Adding edge with invalid source raises error."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="t1", name="T1", tool_id="t1"))

        with pytest.raises(ValueError, match="Source node"):
            dag.add_edge(Edge(source=NodeID("invalid"), target=NodeID("t1")))

    def test_topological_sort_simple(self, simple_dag: DAG):
        """Topological sort returns correct order."""
        order = simple_dag.topological_sort()

        # a must come before b, b must come before c
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_cycle_detection(self):
        """Topological sort detects cycles."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="a"))
        dag = dag.add_node(Node.tool(id="b", name="B", tool_id="b"))
        dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
        dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("a")))  # Cycle!

        with pytest.raises(ValueError, match="Cycle detected"):
            dag.topological_sort()

    def test_validate_empty_dag_raises(self):
        """Validating empty DAG raises error."""
        dag = DAG(name="empty")

        with pytest.raises(ValueError, match="no nodes"):
            dag.validate()

    def test_validate_valid_dag(self):
        """Valid DAG passes validation."""
        dag = DAG(name="valid")
        dag = dag.add_node(Node.tool(id="start", name="Start", tool_id="s"))
        dag = dag.add_node(Node.tool(id="end", name="End", tool_id="e"))
        dag = dag.add_edge(Edge(source=NodeID("start"), target=NodeID("end")))

        assert dag.validate() is True

    def test_to_dict_serialization(self):
        """DAG can be serialized to dict."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="n1", name="Node 1", tool_id="t1"))
        rule = Condition(field="status", operator=ConditionOperator.EQUALS, value="done")
        edge = Edge("n1", "n1", condition=EdgeCondition.JSON_RULE, condition_rule=rule)
        dag = dag.add_edge(edge)

        d = dag.to_dict()

        assert d["name"] == "test"
        assert len(d["nodes"]) == 1
        assert d["nodes"][0]["id"] == "n1"

        assert len(d["edges"]) == 1
        serialized_edge = d["edges"][0]
        assert serialized_edge["condition"] == "json_rule"
        assert serialized_edge["condition_rule"]["field"] == "status"
        assert serialized_edge["condition_rule"]["operator"] == "equals"
        assert serialized_edge["condition_rule"]["value"] == "done"


class TestDAGVisualization:
    """Tests for DAG Mermaid visualization."""

    def test_to_mermaid_basic(self):
        """to_mermaid generates valid mermaid flowchart."""
        dag = DAG(name="test_pipeline")
        dag = dag.add_node(Node.tool(id="fetch", name="Fetch Data", tool_id="fetcher"))
        dag = dag.add_node(Node.skill(id="process", name="Process", skill_id="processor"))
        dag = dag.add_edge(Edge(source=NodeID("fetch"), target=NodeID("process")))

        mermaid = dag.to_mermaid()

        assert "flowchart TD" in mermaid
        assert 'fetch["🔧 Fetch Data"]' in mermaid
        assert 'process("⚡ Process")' in mermaid
        assert "fetch --> process" in mermaid
        # Entry node styling
        assert "style fetch fill:#90EE90" in mermaid

    def test_to_mermaid_all_node_types(self):
        """to_mermaid renders all node types with correct shapes."""
        dag = DAG(name="all_types")
        dag = dag.add_node(Node.tool(id="tool", name="Tool", tool_id="t"))
        dag = dag.add_node(Node.skill(id="skill", name="Skill", skill_id="s"))
        dag = dag.add_node(Node.agent(id="agent", name="Agent", agent_id="a"))
        dag = dag.add_node(Node.router(id="router", name="Router", routes={}))
        dag = dag.add_node(Node.parallel(id="parallel", name="Parallel", parallel_nodes=[]))

        mermaid = dag.to_mermaid()

        # Check shapes: tool=[], skill=(), agent={{}}, router={}, parallel=[[]]
        assert 'tool["🔧 Tool"]' in mermaid
        assert 'skill("⚡ Skill")' in mermaid
        assert 'agent{{"🤖 Agent"}}' in mermaid
        assert 'router{"🔀 Router"}' in mermaid
        assert 'parallel[["⏸ Parallel"]]' in mermaid

    def test_to_mermaid_edge_conditions(self):
        """to_mermaid shows edge conditions."""
        dag = DAG(name="conditions")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="a"))
        dag = dag.add_node(Node.tool(id="b", name="B", tool_id="b"))
        dag = dag.add_node(Node.tool(id="c", name="C", tool_id="c"))
        dag = dag.add_node(Node.tool(id="d", name="D", tool_id="d"))

        dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b"), condition=EdgeCondition.ON_SUCCESS))
        dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("c"), condition=EdgeCondition.ON_FAILURE))

        rule = Condition(field="status", operator=ConditionOperator.EQUALS, value="done")
        dag = dag.add_edge(
            Edge(
                source=NodeID("b"),
                target=NodeID("d"),
                condition=EdgeCondition.JSON_RULE,
                condition_rule=rule,
            )
        )

        mermaid = dag.to_mermaid()

        assert "a -->|✓ success| b" in mermaid
        assert "a -->|✗ failure| c" in mermaid
        assert "b -->|status equals| d" in mermaid

    def test_to_mermaid_direction(self):
        """to_mermaid respects direction parameter."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="a"))

        assert "flowchart TD" in dag.to_mermaid("TD")
        assert "flowchart LR" in dag.to_mermaid("LR")
        assert "flowchart BT" in dag.to_mermaid("BT")
        assert "flowchart RL" in dag.to_mermaid("RL")

    def test_to_mermaid_escapes_special_chars(self):
        """to_mermaid escapes characters that break mermaid syntax."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="n1", name='Node "with" [brackets]', tool_id="t"))

        mermaid = dag.to_mermaid()

        # Double quotes in label should become single quotes
        # Square brackets should become parentheses
        assert "Node 'with' (brackets)" in mermaid
        # The label should be wrapped in outer quotes for mermaid
        assert "[\"🔧 Node 'with' (brackets)\"]" in mermaid

    def test_print_mermaid(self, capsys):
        """print_mermaid outputs to stdout."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="a"))

        dag.print_mermaid()

        captured = capsys.readouterr()
        assert "flowchart TD" in captured.out
        assert 'a["🔧 A"]' in captured.out

    def test_save_mermaid_raw(self, tmp_path):
        """save_mermaid saves raw mermaid to file."""
        dag = DAG(name="test")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="a"))

        filepath = tmp_path / "dag.mmd"
        dag.save_mermaid(str(filepath))

        content = filepath.read_text()
        assert "flowchart TD" in content
        assert "```" not in content  # No markdown fence

    def test_save_mermaid_markdown(self, tmp_path):
        """save_mermaid wraps in markdown fence for .md files."""
        dag = DAG(name="test_dag", description="A test DAG")
        dag = dag.add_node(Node.tool(id="a", name="A", tool_id="a"))

        filepath = tmp_path / "dag.md"
        dag.save_mermaid(str(filepath))

        content = filepath.read_text()
        assert "# test_dag" in content
        assert "A test DAG" in content
        assert "```mermaid" in content
        assert "flowchart TD" in content
        assert "```" in content
