"""ContextNodeExecutor - Bridges DAG nodes to agents via registry."""

import hashlib
import json
import logging
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult
from cemaf.agents.protocols import Agent
from cemaf.agents.registry import AgentRegistry
from cemaf.context.context import Context
from cemaf.core.domain import DomainContext
from cemaf.core.provenance import ProvenanceLink, SourceReference
from cemaf.core.types import AgentID, NodeID, ProvenanceID
from cemaf.core.utils import utc_now
from cemaf.llm.instrumented import InstrumentedLLMClient
from cemaf.llm.protocols import LLMClient
from cemaf.memory.manager import MemoryManager
from cemaf.memory.semantic import MemoryQuery
from cemaf.memory.session import SessionManager
from cemaf.observability.run_logger import RunLogger
from cemaf.orchestration.dag import Node
from cemaf.orchestration.executor import NodeResult
from cemaf.retrieval.protocols import VectorStore

logger = logging.getLogger(__name__)


class ContextNodeExecutor:
    """Executes AGENT nodes by resolving ref_id to agents via registry."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        run_logger: RunLogger | None = None,
        domain_context: DomainContext | None = None,
        llm_client: LLMClient | None = None,
        vector_store: VectorStore | None = None,
        memory_manager: MemoryManager | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        """Initialize with registry and optional logger/domain context."""
        self._registry = agent_registry
        self._run_logger = run_logger
        self._domain_context = domain_context
        self._llm_client = llm_client
        self._vector_store = vector_store
        self._memory_manager = memory_manager
        self._session_manager = session_manager

    async def execute_node(
        self,
        node: Node,
        context: Context,
    ) -> NodeResult:
        """Execute a single node by dispatching to the appropriate agent."""
        start = perf_counter()

        agent_name = node.ref_id
        if not agent_name:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Node {node.id} has no ref_id (agent name)",
            )

        # Resolve agent from registry (registered first, then built-in)
        agent: Agent[Any, Any] | None = self._registry.get(agent_name)
        if agent is None:
            instrumented_client = self._instrument_client(
                node_id=str(node.id),
                agent_id=agent_name,
            )
            # InstrumentedLLMClient satisfies LLMClient protocol structurally
            effective_client: LLMClient | None = instrumented_client or self._llm_client  # type: ignore[assignment]
            agent = self._registry.create_agent(
                agent_name,
                llm_client=effective_client,
                vector_store=self._vector_store,
            )
        if agent is None:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Agent '{agent_name}' not found in registry",
            )

        # Build goal from resolved inputs
        resolved_inputs = context.get("_resolved_inputs", default=node.input_mapping)
        goal = self._build_goal(agent_name=agent_name, inputs=resolved_inputs)
        if goal is None:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Failed to build goal for agent '{agent_name}'",
            )

        # Populate global_memory from memory system if available
        run_id = str(context.get("_run_id", default=""))
        global_memory = await self._recall_global_memory(agent_name=agent_name)

        # Build agent context
        agent_context = AgentContext(
            run_id=run_id,
            agent_id=agent_name,
            domain_context=self._domain_context,
            global_memory=global_memory,
        )

        # Compute context hash for provenance
        context_hash = self._compute_context_hash(inputs=resolved_inputs)

        try:
            result = await agent.run(goal=goal, context=agent_context)
            duration_ms = (perf_counter() - start) * 1000

            # Build provenance link
            if self._run_logger:
                link = ProvenanceLink(
                    id=ProvenanceID(f"prov_{node.id}_{utc_now().isoformat()}"),
                    llm_call_id=f"llm_{node.id}",
                    node_id=NodeID(str(node.id)),
                    agent_id=AgentID(agent_name),
                    context_sources=self._extract_source_refs(inputs=resolved_inputs),
                    context_hash=context_hash,
                    budget_utilization=0.0,
                    cost_usd=0.0,
                )
                self._run_logger.record_provenance_link(link=link)

            if result.success:
                output = self._extract_output(result=result)

                # Ingest successful result into session memory
                await self._ingest_result(
                    agent_name=agent_name,
                    output=output,
                    run_id=run_id,
                )

                return NodeResult(
                    node_id=node.id,
                    success=True,
                    output=output,
                    duration_ms=duration_ms,
                    metadata={
                        "agent_id": agent_name,
                        "context_hash": context_hash,
                    },
                )
            else:
                return NodeResult(
                    node_id=node.id,
                    success=False,
                    error=result.error or f"Agent '{agent_name}' failed",
                    duration_ms=duration_ms,
                    metadata={"agent_id": agent_name},
                )

        except Exception as e:
            duration_ms = (perf_counter() - start) * 1000
            logger.error("Agent '%s' raised exception: %s", agent_name, e, exc_info=True)
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                metadata={"agent_id": agent_name},
            )

    def _build_goal(self, *, agent_name: str, inputs: dict[str, Any] | Any) -> BaseModel | None:
        """Build a goal model from resolved inputs."""
        goal_type = self._registry.get_goal_type(agent_name=agent_name)
        if goal_type is None:
            return None

        if not isinstance(inputs, dict):
            return None

        try:
            return goal_type(**inputs)
        except Exception as e:
            logger.warning("Failed to build goal for '%s': %s", agent_name, e)
            return None

    def _extract_output(self, *, result: AgentResult[Any]) -> str | None:
        """Extract serializable output from agent result."""
        output = result.output
        if output is None:
            return None
        if hasattr(output, "model_dump"):
            dumped = output.model_dump()
            return json.dumps(dumped)
        return str(output)

    def _compute_context_hash(self, *, inputs: dict[str, Any] | Any) -> str:
        """Compute deterministic hash of context inputs."""
        try:
            serialized = json.dumps(inputs, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(inputs)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _instrument_client(
        self,
        *,
        node_id: str,
        agent_id: str,
    ) -> InstrumentedLLMClient | None:
        """Wrap the LLM client with instrumentation if RunLogger is active."""
        if self._llm_client is None or self._run_logger is None:
            return None
        return InstrumentedLLMClient(
            client=self._llm_client,
            run_logger=self._run_logger,
            node_id=node_id,
            agent_id=agent_id,
        )

    def _extract_source_refs(self, *, inputs: dict[str, Any] | Any) -> tuple[SourceReference, ...]:
        """Extract source references from resolved inputs for provenance."""
        if not isinstance(inputs, dict):
            return ()
        refs: list[SourceReference] = []
        for key, value in inputs.items():
            refs.append(
                SourceReference(
                    source_id=key,
                    source_type="resolved_input",
                    token_count=len(str(value)) // 4,
                    priority=0,
                    included=True,
                )
            )
        return tuple(refs)

    async def _recall_global_memory(self, *, agent_name: str) -> dict[str, Any]:
        """Load relevant memories for the agent from the memory system."""
        if self._memory_manager is None:
            return {}
        try:
            results = await self._memory_manager.recall(
                query=MemoryQuery(text=agent_name, limit=10),
            )
            return {r.item.key: r.item.value for r in results}
        except Exception:
            logger.warning("Failed to recall memory for '%s'", agent_name, exc_info=True)
            return {}

    async def _ingest_result(
        self,
        *,
        agent_name: str,
        output: str | None,
        run_id: str,
    ) -> None:
        """Store agent result in session memory."""
        if self._session_manager is None or not output:
            return
        try:
            await self._session_manager.ingest(
                session_id=run_id,
                key=f"{agent_name}_output",
                value={"output": output, "agent": agent_name},
            )
        except Exception:
            logger.warning("Failed to ingest result for '%s'", agent_name, exc_info=True)
