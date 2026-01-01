"""
DAG (Directed Acyclic Graph) for workflow definition.

DAGs are:
- DYNAMIC: Built at runtime based on context
- COMPOSABLE: Can nest DAGs within DAGs
- VALIDATED: Cycle detection, dependency resolution
- SERIALIZABLE: Can be saved/loaded as JSON
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from cemaf.context.context import Context  # New import
from cemaf.core.enums import NodeType
from cemaf.core.types import JSON, NodeID


class ConditionOperator(str, Enum):
    """Operators for serializable conditions."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    CONTAINS = "contains"
    IS_NONE = "is_none"
    IS_NOT_NONE = "is_not_none"


@dataclass(frozen=True)
class Condition:
    """
    A serializable, JSON-based condition for rule evaluation.

    The `field` supports dot notation for nested lookups (e.g., "data.result.count").
    """

    field: str  # The key to check in the context (supports dot notation)
    operator: ConditionOperator
    value: Any | None = None  # The value to compare against

    def evaluate(self, context: Context) -> bool:  # Updated signature
        """Evaluate the condition against a given context."""
        current_val = context.get(self.field, default=None)  # Use Context.get()

        # Perform comparison
        op = self.operator
        if op == ConditionOperator.EQUALS:
            return current_val == self.value
        if op == ConditionOperator.NOT_EQUALS:
            return current_val != self.value
        if op == ConditionOperator.GREATER_THAN:
            return (
                current_val is not None and self.value is not None and current_val > self.value
            )  # Added None checks
        if op == ConditionOperator.LESS_THAN:
            return (
                current_val is not None and self.value is not None and current_val < self.value
            )  # Added None checks
        if op == ConditionOperator.CONTAINS:
            return isinstance(current_val, (list, str, dict)) and self.value in current_val
        if op == ConditionOperator.IS_NONE:
            return current_val is None
        if op == ConditionOperator.IS_NOT_NONE:
            return current_val is not None

        return False  # Should not be reached


class EdgeCondition(str, Enum):
    """Condition for edge traversal."""

    ALWAYS = "always"  # Always traverse
    ON_SUCCESS = "on_success"  # Only if previous succeeded
    ON_FAILURE = "on_failure"  # Only if previous failed
    JSON_RULE = "json_rule"  # Use a serializable rule


@dataclass(frozen=True)
class Edge:
    """
    Connection between two nodes in a DAG.

    Edges can be conditional - only traverse if condition is met.
    """

    source: NodeID
    target: NodeID
    condition: EdgeCondition = EdgeCondition.ALWAYS
    condition_rule: Condition | None = None
    metadata: JSON = field(default_factory=dict)

    def should_traverse(self, context: Context) -> bool:  # Updated signature
        """Check if this edge should be traversed given context."""
        if self.condition == EdgeCondition.ALWAYS:
            return True
        if self.condition == EdgeCondition.JSON_RULE and self.condition_rule:
            return self.condition_rule.evaluate(context)
        # ON_SUCCESS/ON_FAILURE checked by executor
        return True


@dataclass(frozen=True)
class Node:
    """
    A node in a DAG - represents a unit of execution.

    Nodes can be:
    - TOOL: Execute a tool directly
    - SKILL: Execute a skill
    - AGENT: Execute an agent (can spawn sub-DAGs)
    - ROUTER: Route to different paths based on condition
    - PARALLEL: Execute multiple paths in parallel
    """

    id: NodeID
    type: NodeType
    name: str
    description: str = ""

    # Reference to the executable (tool_id, skill_id, or agent_id)
    ref_id: str = ""

    # Configuration for this node
    config: JSON = field(default_factory=dict)

    # Input/output mapping
    input_mapping: JSON = field(default_factory=dict)  # Map from context to node input
    output_key: str = ""  # Key to store output in context

    # Retry configuration
    max_retries: int = 3
    retry_on_failure: bool = True

    # For PARALLEL nodes: list of sub-node IDs to run in parallel
    parallel_nodes: tuple[NodeID, ...] = field(default_factory=tuple)

    # For ROUTER nodes: mapping of condition -> target node
    routes: JSON = field(default_factory=dict)

    @classmethod
    def tool(
        cls,
        id: str,
        name: str,
        tool_id: str,
        description: str = "",
        input_mapping: JSON | None = None,
        output_key: str = "",
    ) -> Node:
        """Create a tool node."""
        return cls(
            id=NodeID(id),
            type=NodeType.TOOL,
            name=name,
            description=description,
            ref_id=tool_id,
            input_mapping=input_mapping or {},
            output_key=output_key,
        )

    @classmethod
    def skill(
        cls,
        id: str,
        name: str,
        skill_id: str,
        description: str = "",
        input_mapping: JSON | None = None,
        output_key: str = "",
    ) -> Node:
        """Create a skill node."""
        return cls(
            id=NodeID(id),
            type=NodeType.SKILL,
            name=name,
            description=description,
            ref_id=skill_id,
            input_mapping=input_mapping or {},
            output_key=output_key,
        )

    @classmethod
    def agent(
        cls,
        id: str,
        name: str,
        agent_id: str,
        description: str = "",
        config: JSON | None = None,
        output_key: str = "",
    ) -> Node:
        """Create an agent node."""
        return cls(
            id=NodeID(id),
            type=NodeType.AGENT,
            name=name,
            description=description,
            ref_id=agent_id,
            config=config or {},
            output_key=output_key,
        )

    @classmethod
    def router(
        cls,
        id: str,
        name: str,
        routes: dict[str, str],
        description: str = "",
    ) -> Node:
        """Create a router node."""
        return cls(
            id=NodeID(id),
            type=NodeType.ROUTER,
            name=name,
            description=description,
            routes=routes,
        )

    @classmethod
    def conditional(
        cls,
        id: str,
        name: str,
        condition: Condition | Callable[[Context], bool] | str | None = None,
        *,
        routes: dict[bool | str, str] | None = None,
        description: str = "",
        output_key: str = "",
        config: JSON | None = None,
    ) -> Node:
        """Create a conditional node.

        The node evaluates a condition (callable, context key, or ``Condition``)
        and routes execution based on the boolean result.
        """

        base_config = dict(config) if isinstance(config, dict) else {}

        if isinstance(condition, Condition):
            base_config.setdefault("condition_rule", condition)
        elif callable(condition):
            base_config.setdefault("condition_fn", condition)
        elif isinstance(condition, str) and condition:
            base_config.setdefault("condition_key", condition)

        node_routes = routes or {}

        return cls(
            id=NodeID(id),
            type=NodeType.CONDITIONAL,
            name=name,
            description=description,
            config=base_config,
            output_key=output_key,
            routes=node_routes,
        )

    @classmethod
    def parallel(
        cls,
        id: str,
        name: str,
        parallel_nodes: list[str],
        description: str = "",
        output_key: str = "",  # New parameter
    ) -> Node:
        """Create a parallel execution node."""
        return cls(
            id=NodeID(id),
            type=NodeType.PARALLEL,
            name=name,
            description=description,
            parallel_nodes=tuple(NodeID(n) for n in parallel_nodes),
            output_key=output_key,  # Pass new parameter
        )


class DAG(BaseModel):
    """
    Directed Acyclic Graph for workflow definition.

    DAGs are built dynamically at runtime and can be nested.

    Example:
        dag = DAG(name="content_pipeline")

        # Add nodes
        dag = dag.add_node(Node.skill("fetch", "Fetch Data", "data_fetch"))
        dag = dag.add_node(Node.agent("analyze", "Analyze", "analyst"))
        dag = dag.add_node(Node.skill("export", "Export", "exporter"))

        # Add edges
        dag = dag.add_edge(Edge("fetch", "analyze"))
        dag = dag.add_edge(Edge("analyze", "export"))

        # Validate
        dag.validate()  # Raises if cycles or invalid
    """

    model_config = {"frozen": True}

    name: str
    description: str = ""
    nodes: tuple[Node, ...] = Field(default_factory=tuple)
    edges: tuple[Edge, ...] = Field(default_factory=tuple)
    entry_node: NodeID | None = None
    metadata: JSON = Field(default_factory=dict)

    def add_node(self, node: Node) -> DAG:
        """Add a node and return new DAG."""
        if any(n.id == node.id for n in self.nodes):
            raise ValueError(f"Node {node.id} already exists")

        new_nodes = self.nodes + (node,)
        entry = self.entry_node or node.id
        return self.model_copy(update={"nodes": new_nodes, "entry_node": entry})

    def add_edge(self, edge: Edge) -> DAG:
        """Add an edge and return new DAG."""
        # Validate nodes exist
        node_ids = {n.id for n in self.nodes}
        if edge.source not in node_ids:
            raise ValueError(f"Source node {edge.source} not found")
        if edge.target not in node_ids:
            raise ValueError(f"Target node {edge.target} not found")

        new_edges = self.edges + (edge,)
        return self.model_copy(update={"edges": new_edges})

    def get_node(self, node_id: NodeID) -> Node | None:
        """Get a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_outgoing_edges(self, node_id: NodeID) -> tuple[Edge, ...]:
        """Get all edges starting from a node."""
        return tuple(e for e in self.edges if e.source == node_id)

    def get_incoming_edges(self, node_id: NodeID) -> tuple[Edge, ...]:
        """Get all edges ending at a node."""
        return tuple(e for e in self.edges if e.target == node_id)

    def topological_sort(self) -> tuple[NodeID, ...]:
        """
        Return nodes in topological order.

        Raises ValueError if cycle detected.
        """
        # Build adjacency list
        graph: dict[NodeID, list[NodeID]] = {n.id: [] for n in self.nodes}
        in_degree: dict[NodeID, int] = {n.id: 0 for n in self.nodes}

        for edge in self.edges:
            graph[edge.source].append(edge.target)
            in_degree[edge.target] += 1

        # Kahn's algorithm
        queue = [n for n, d in in_degree.items() if d == 0]
        result: list[NodeID] = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self.nodes):
            raise ValueError("Cycle detected in DAG")

        return tuple(result)

    def validate(self) -> bool:
        """
        Validate the DAG structure.

        Checks:
        - No cycles
        - Entry node exists
        - All edges reference valid nodes

        Raises ValueError on invalid DAG.
        """
        if not self.nodes:
            raise ValueError("DAG has no nodes")

        if not self.entry_node:
            raise ValueError("DAG has no entry node")

        if not self.get_node(self.entry_node):
            raise ValueError(f"Entry node {self.entry_node} not found")

        # This also checks for cycles
        self.topological_sort()

        return True

    def to_dict(self) -> JSON:
        """Serialize DAG to JSON-compatible dict."""

        def serialize_edge(edge: Edge) -> JSON:
            data: JSON = {
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition.value,
            }
            if edge.condition_rule:
                data["condition_rule"] = {
                    "field": edge.condition_rule.field,
                    "operator": edge.condition_rule.operator.value,
                    "value": edge.condition_rule.value,
                }
            return data

        return {
            "name": self.name,
            "description": self.description,
            "entry_node": self.entry_node,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "name": n.name,
                    "description": n.description,
                    "ref_id": n.ref_id,
                    "config": n.config,
                    "input_mapping": n.input_mapping,
                    "output_key": n.output_key,
                }
                for n in self.nodes
            ],
            "edges": [serialize_edge(e) for e in self.edges],
            "metadata": self.metadata,
        }

    def to_mermaid(self, direction: str = "TD") -> str:
        """
        Generate a Mermaid flowchart representation of this DAG.

        Args:
            direction: Flow direction - "TD" (top-down), "LR" (left-right),
                      "BT" (bottom-top), "RL" (right-left)

        Returns:
            Mermaid flowchart code as a string.

        Example:
            >>> print(dag.to_mermaid())
            flowchart TD
                fetch[📥 Fetch Data]
                analyze{{🤖 Analyze}}
                export[📤 Export]
                fetch --> analyze
                analyze --> export

        Node shapes by type:
            - TOOL: [rectangle]
            - SKILL: (rounded)
            - AGENT: {{hexagon}}
            - ROUTER: {diamond}
            - PARALLEL: [[stadium]]
            - CONDITIONAL: {diamond}
        """
        lines = [f"flowchart {direction}"]

        # Node type to shape mapping
        shape_map = {
            NodeType.TOOL: ("[", "]"),
            NodeType.SKILL: ("(", ")"),
            NodeType.AGENT: ("{{", "}}"),
            NodeType.ROUTER: ("{", "}"),
            NodeType.PARALLEL: ("[[", "]]"),
            NodeType.CONDITIONAL: ("{", "}"),
        }

        # Node type to emoji
        emoji_map = {
            NodeType.TOOL: "🔧",
            NodeType.SKILL: "⚡",
            NodeType.AGENT: "🤖",
            NodeType.ROUTER: "🔀",
            NodeType.PARALLEL: "⏸",
            NodeType.CONDITIONAL: "❓",
        }

        # Generate node definitions
        for node in self.nodes:
            left, right = shape_map.get(node.type, ("[", "]"))
            emoji = emoji_map.get(node.type, "")
            # Escape special mermaid characters in name
            safe_name = node.name.replace('"', "'").replace("[", "(").replace("]", ")")
            label = f"{emoji} {safe_name}".strip()
            lines.append(f'    {node.id}{left}"{label}"{right}')

        # Generate edges
        for edge in self.edges:
            arrow = "-->"
            label = ""

            if edge.condition == EdgeCondition.ON_SUCCESS:
                label = "|✓ success|"
            elif edge.condition == EdgeCondition.ON_FAILURE:
                label = "|✗ failure|"
            elif edge.condition == EdgeCondition.JSON_RULE and edge.condition_rule:
                rule = edge.condition_rule
                label = f"|{rule.field} {rule.operator.value}|"

            lines.append(f"    {edge.source} {arrow}{label} {edge.target}")

        # Add styling for entry node
        if self.entry_node:
            lines.append(f"    style {self.entry_node} fill:#90EE90,stroke:#228B22")

        return "\n".join(lines)

    def print_mermaid(self, direction: str = "TD") -> None:
        """Print Mermaid diagram to stdout for quick visualization."""
        print(self.to_mermaid(direction))

    def save_mermaid(self, path: str, direction: str = "TD") -> None:
        """
        Save Mermaid diagram to a file.

        Args:
            path: File path (e.g., "dag.mmd" or "dag.md")
            direction: Flow direction

        The output can be:
        - Rendered with Mermaid CLI: `mmdc -i dag.mmd -o dag.png`
        - Viewed in Mermaid Live Editor: https://mermaid.live
        - Embedded in Markdown: wrap in ```mermaid ... ``` code fence
        """
        from pathlib import Path

        content = self.to_mermaid(direction)

        # If it's a markdown file, wrap in mermaid fence
        if path.endswith(".md"):
            content = f"# {self.name}\n\n{self.description}\n\n```mermaid\n{content}\n```\n"

        Path(path).write_text(content)
