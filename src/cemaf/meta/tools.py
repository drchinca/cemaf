"""Meta-tools — CEMAF self-introspection, DAG generation, trace analysis, and knowledge graph."""

from __future__ import annotations

from typing import Any

from cemaf.agents.registry import AgentRegistry
from cemaf.audit.models import AuditEntry
from cemaf.audit.protocols import AuditTrail
from cemaf.core.result import Result
from cemaf.core.types import JSON, NodeID, ToolID
from cemaf.knowledge.models import EntityType, KGEntity, KGRelation, RelationType
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.tools.base import Tool, ToolResult, ToolSchema
from cemaf.tools.registry import ToolRegistry


class IntrospectRegistryTool(Tool):
    """Query agent and tool registries for available capabilities."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
    ) -> None:
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry

    @property
    def id(self) -> ToolID:
        return ToolID("meta_introspect_registry")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="meta_introspect_registry",
            description="Query agent and tool registries for available capabilities.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional filter term for registry entries.",
                    },
                    "registry_type": {
                        "type": "string",
                        "enum": ["agents", "tools", "both"],
                        "description": "Which registry to query.",
                    },
                },
            },
            required=("registry_type",),
            is_read_only=True,
            is_concurrent_safe=True,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Return structured capabilities from the requested registries."""
        registry_type: str = kwargs.get("registry_type", "both")
        query: str = kwargs.get("query", "")

        try:
            result: JSON = {}

            if registry_type in ("agents", "both"):
                agents = self._agent_registry.list_agents()
                if query:
                    agents = [a for a in agents if query.lower() in a.lower()]

                agent_details: list[JSON] = []
                for agent_id in agents:
                    detail: JSON = {"id": agent_id}
                    goal_type = self._agent_registry.get_goal_type(agent_id)
                    if goal_type is not None and hasattr(goal_type, "model_fields"):
                        detail["goal_fields"] = {
                            fname: str(finfo.annotation) for fname, finfo in goal_type.model_fields.items()
                        }
                    agent_details.append(detail)

                result["agents"] = agent_details
                result["capabilities_description"] = self._agent_registry.get_capabilities_description()

            if registry_type in ("tools", "both"):
                schemas = self._tool_registry.to_schemas()
                tool_entries: list[JSON] = []
                for s in schemas:
                    if query and query.lower() not in s.name.lower():
                        continue
                    tool_entries.append(
                        {
                            "name": s.name,
                            "description": s.description,
                            "parameters": s.parameters,
                            "required": list(s.required),
                            "safety": {
                                "is_concurrent_safe": s.is_concurrent_safe,
                                "is_read_only": s.is_read_only,
                                "is_destructive": s.is_destructive,
                            },
                        }
                    )
                result["tools"] = tool_entries

            return Result.ok(data=result)
        except Exception as exc:
            return Result.fail(error=f"Introspection failed: {exc}")


class GenerateDAGTool(Tool):
    """Create a validated DAG from a declarative node/edge specification."""

    @property
    def id(self) -> ToolID:
        return ToolID("meta_generate_dag")

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="meta_generate_dag",
            description="Create a validated DAG from a declarative specification of nodes and edges.",
            is_concurrent_safe=True,
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "DAG name."},
                    "description": {"type": "string", "description": "DAG description."},
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "type": {"type": "string", "enum": ["agent", "tool"]},
                                "name": {"type": "string"},
                                "ref_id": {"type": "string"},
                                "output_key": {"type": "string"},
                            },
                            "required": ["id", "type", "name", "ref_id"],
                        },
                        "description": "Node specifications.",
                    },
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                            },
                            "required": ["source", "target"],
                        },
                        "description": "Edge specifications.",
                    },
                },
            },
            required=("name", "nodes", "edges"),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Build, validate, and return a DAG from the provided spec."""
        name: str = kwargs.get("name", "")
        description: str = kwargs.get("description", "")
        nodes_spec: list[dict[str, Any]] = kwargs.get("nodes", [])
        edges_spec: list[dict[str, Any]] = kwargs.get("edges", [])

        if not name:
            return Result.fail(error="DAG name is required")
        if not nodes_spec:
            return Result.fail(error="At least one node is required")

        try:
            dag = DAG(name=name, description=description)

            for spec in nodes_spec:
                node_id = spec.get("id", "")
                node_type = spec.get("type", "")
                node_name = spec.get("name", "")
                ref_id = spec.get("ref_id", "")
                output_key = spec.get("output_key", "")

                if not node_id or not node_name or not ref_id:
                    return Result.fail(error=f"Node spec missing required fields: {spec}")

                if node_type == "agent":
                    node = Node.agent(
                        id=node_id,
                        name=node_name,
                        agent_id=ref_id,
                        output_key=output_key,
                    )
                elif node_type == "tool":
                    node = Node.tool(
                        id=node_id,
                        name=node_name,
                        tool_id=ref_id,
                        output_key=output_key,
                    )
                else:
                    return Result.fail(error=f"Unknown node type: {node_type!r}")

                dag = dag.add_node(node=node)

            for spec in edges_spec:
                source = spec.get("source", "")
                target = spec.get("target", "")
                if not source or not target:
                    return Result.fail(error=f"Edge spec missing source or target: {spec}")
                edge = Edge(
                    source=NodeID(source),
                    target=NodeID(target),
                )
                dag = dag.add_edge(edge=edge)

            dag.validate_structure()
            return Result.ok(data=dag.to_dict())

        except ValueError as exc:
            return Result.fail(error=str(exc))
        except Exception as exc:
            return Result.fail(error=f"DAG generation failed: {exc}")


class TraceAnalyzerTool(Tool):
    """Query audit trail for execution timeline, quality trends, and anomalies."""

    def __init__(self, *, audit_trail: AuditTrail) -> None:
        self._audit_trail = audit_trail

    @property
    def id(self) -> ToolID:
        return ToolID("meta_trace_analyzer")

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="meta_trace_analyzer",
            description="Analyze execution traces via the audit trail.",
            is_read_only=True,
            is_concurrent_safe=True,
            parameters={
                "type": "object",
                "properties": {
                    "analysis_type": {
                        "type": "string",
                        "enum": ["timeline", "quality_trend", "anomalies"],
                        "description": "Type of analysis to perform.",
                    },
                    "run_id": {
                        "type": "string",
                        "description": "Run ID (required for timeline analysis).",
                    },
                    "window": {
                        "type": "integer",
                        "description": "Rolling window size for quality trend.",
                        "default": 20,
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Standard deviation threshold for anomaly detection.",
                        "default": 2.0,
                    },
                },
            },
            required=("analysis_type",),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Delegate to the appropriate audit trail analysis method."""
        analysis_type: str = kwargs.get("analysis_type", "")
        run_id: str | None = kwargs.get("run_id")
        window: int = kwargs.get("window", 20)
        threshold: float = kwargs.get("threshold", 2.0)

        try:
            if analysis_type == "timeline":
                if not run_id:
                    return Result.fail(error="run_id is required for timeline analysis")
                entries = await self._audit_trail.get_run_timeline(run_id=run_id)
                return Result.ok(data=_serialize_audit_entries(entries=entries))

            if analysis_type == "quality_trend":
                trend = await self._audit_trail.get_quality_trend(window=window)
                return Result.ok(data={"trend": list(trend), "window": window})

            if analysis_type == "anomalies":
                entries = await self._audit_trail.get_anomalies(threshold=threshold)
                return Result.ok(
                    data={
                        "anomalies": _serialize_audit_entries(entries=entries),
                        "threshold": threshold,
                    }
                )

            return Result.fail(error=f"Unknown analysis_type: {analysis_type!r}")

        except Exception as exc:
            return Result.fail(error=f"Trace analysis failed: {exc}")


class KnowledgeGraphTool(Tool):
    """CRUD operations on the CEMAF knowledge graph."""

    def __init__(self, *, knowledge_graph: KnowledgeGraph) -> None:
        self._knowledge_graph = knowledge_graph

    @property
    def id(self) -> ToolID:
        return ToolID("meta_knowledge_graph")

    @property
    def is_destructive(self) -> bool:
        return True  # remove_entity is destructive

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="meta_knowledge_graph",
            description="Perform CRUD operations on the knowledge graph.",
            is_destructive=True,
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "add_entity",
                            "add_relation",
                            "get_entity",
                            "search",
                            "query_neighbors",
                            "remove_entity",
                        ],
                        "description": "Knowledge graph operation to perform.",
                    },
                    "entity": {
                        "type": "object",
                        "description": "Entity data for add_entity.",
                    },
                    "relation": {
                        "type": "object",
                        "description": "Relation data for add_relation.",
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "Entity ID for get_entity, query_neighbors, or remove_entity.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query text.",
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "Optional entity type filter for search.",
                    },
                    "relation_type": {
                        "type": "string",
                        "description": "Optional relation type filter for query_neighbors.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results for search.",
                        "default": 10,
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Traversal depth for query_neighbors.",
                        "default": 1,
                    },
                },
            },
            required=("operation",),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Route to the appropriate knowledge graph operation."""
        operation: str = kwargs.get("operation", "")

        try:
            if operation == "add_entity":
                return await self._handle_add_entity(entity_data=kwargs.get("entity"))

            if operation == "add_relation":
                return await self._handle_add_relation(relation_data=kwargs.get("relation"))

            if operation == "get_entity":
                entity_id = kwargs.get("entity_id", "")
                if not entity_id:
                    return Result.fail(error="entity_id is required for get_entity")
                entity = await self._knowledge_graph.get_entity(entity_id=entity_id)
                if entity is None:
                    return Result.ok(data=None, metadata={"found": False})
                return Result.ok(data=entity.to_dict(), metadata={"found": True})

            if operation == "search":
                query = kwargs.get("query", "")
                if not query:
                    return Result.fail(error="query is required for search")
                entity_type = _parse_entity_type(raw=kwargs.get("entity_type"))
                limit: int = kwargs.get("limit", 10)
                entities = await self._knowledge_graph.search(
                    query=query,
                    entity_type=entity_type,
                    limit=limit,
                )
                return Result.ok(data=[e.to_dict() for e in entities])

            if operation == "query_neighbors":
                entity_id = kwargs.get("entity_id", "")
                if not entity_id:
                    return Result.fail(error="entity_id is required for query_neighbors")
                rel_type = _parse_relation_type(raw=kwargs.get("relation_type"))
                depth: int = kwargs.get("depth", 1)
                result = await self._knowledge_graph.query_neighbors(
                    entity_id=entity_id,
                    relation_type=rel_type,
                    depth=depth,
                )
                return Result.ok(
                    data={
                        "entities": [e.to_dict() for e in result.entities],
                        "relations": [r.to_dict() for r in result.relations],
                    }
                )

            if operation == "remove_entity":
                entity_id = kwargs.get("entity_id", "")
                if not entity_id:
                    return Result.fail(error="entity_id is required for remove_entity")
                removed = await self._knowledge_graph.remove_entity(entity_id=entity_id)
                return Result.ok(data={"removed": removed, "entity_id": entity_id})

            return Result.fail(error=f"Unknown operation: {operation!r}")

        except Exception as exc:
            return Result.fail(error=f"Knowledge graph operation failed: {exc}")

    async def _handle_add_entity(self, entity_data: dict[str, Any] | None) -> ToolResult:
        """Construct a KGEntity from dict and add it to the graph."""
        if not entity_data:
            return Result.fail(error="entity dict is required for add_entity")

        entity_id = entity_data.get("id", "")
        entity_type_raw = entity_data.get("type", "")
        name = entity_data.get("name", "")

        if not entity_id or not entity_type_raw or not name:
            return Result.fail(error="entity requires id, type, and name fields")

        try:
            entity_type = EntityType(entity_type_raw)
        except ValueError:
            return Result.fail(
                error=f"Invalid entity type: {entity_type_raw!r}. "
                f"Valid types: {[t.value for t in EntityType]}"
            )

        entity = KGEntity(
            id=entity_id,
            type=entity_type,
            name=name,
            description=entity_data.get("description", ""),
            properties=entity_data.get("properties", {}),
        )
        await self._knowledge_graph.add_entity(entity=entity)
        return Result.ok(data=entity.to_dict())

    async def _handle_add_relation(self, relation_data: dict[str, Any] | None) -> ToolResult:
        """Construct a KGRelation from dict and add it to the graph."""
        if not relation_data:
            return Result.fail(error="relation dict is required for add_relation")

        source_id = relation_data.get("source_id", "")
        target_id = relation_data.get("target_id", "")
        rel_type_raw = relation_data.get("type", "")

        if not source_id or not target_id or not rel_type_raw:
            return Result.fail(error="relation requires source_id, target_id, and type fields")

        try:
            rel_type = RelationType(rel_type_raw)
        except ValueError:
            return Result.fail(
                error=f"Invalid relation type: {rel_type_raw!r}. "
                f"Valid types: {[t.value for t in RelationType]}"
            )

        relation = KGRelation(
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            properties=relation_data.get("properties", {}),
        )
        await self._knowledge_graph.add_relation(relation=relation)
        return Result.ok(data=relation.to_dict())


def _serialize_audit_entries(*, entries: tuple[AuditEntry, ...]) -> list[JSON]:
    """Convert audit entries to serializable dicts."""
    return [
        {
            "id": e.id,
            "type": e.type.value,
            "timestamp": e.timestamp.isoformat(),
            "run_id": e.run_id,
            "source": e.source,
            "payload": e.payload,
        }
        for e in entries
    ]


def _parse_entity_type(*, raw: str | None) -> EntityType | None:
    """Parse an optional entity type string to the enum."""
    if not raw:
        return None
    try:
        return EntityType(raw)
    except ValueError:
        return None


def _parse_relation_type(*, raw: str | None) -> RelationType | None:
    """Parse an optional relation type string to the enum."""
    if not raw:
        return None
    try:
        return RelationType(raw)
    except ValueError:
        return None
