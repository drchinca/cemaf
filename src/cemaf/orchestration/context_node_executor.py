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
from cemaf.agents.selection import AgentSelector, Bid, BidContext, Capability
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, ContextCompiler
from cemaf.context.context import Context
from cemaf.core.domain import DomainContext
from cemaf.core.provenance import ProvenanceLink, SourceReference
from cemaf.core.types import AgentID, NodeID, ProvenanceID
from cemaf.core.utils import utc_now
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.council import AgentCouncil
from cemaf.council.protocols import CouncilMember, VoteAggregator
from cemaf.council.types import AggregationMethod, CouncilConfig, CouncilQuestion
from cemaf.llm.instrumented import InstrumentedLLMClient
from cemaf.llm.protocols import LLMClient
from cemaf.memory.manager import MemoryManager
from cemaf.memory.semantic import MemoryQuery
from cemaf.memory.session import SessionManager
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.run_logger import RunLogger
from cemaf.orchestration.blueprint_hook import BlueprintSelectorHook
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
        context_compiler: ContextCompiler | None = None,
        token_budget: TokenBudget | None = None,
        blueprint_selector: BlueprintSelectorHook | None = None,
        agent_selector: AgentSelector | None = None,
        budget_guard: BudgetGuard | None = None,
        council_aggregator: VoteAggregator | None = None,
    ) -> None:
        """Initialize with registry and optional compiler/budget for context compilation."""
        self._registry = agent_registry
        self._run_logger = run_logger
        self._domain_context = domain_context
        self._llm_client = llm_client
        self._vector_store = vector_store
        self._memory_manager = memory_manager
        self._session_manager = session_manager
        self._context_compiler = context_compiler
        self._token_budget = token_budget
        self._blueprint_selector = blueprint_selector
        self._agent_selector = agent_selector
        self._budget_guard = budget_guard
        self._council_aggregator = council_aggregator

    async def execute_node(
        self,
        node: Node,
        context: Context,
    ) -> NodeResult:
        """Execute a single node by dispatching to the appropriate agent."""
        start = perf_counter()

        # Resolved inputs (post $$ref$$ resolution) — read once, shared by the
        # auction's goal_text and the goal builder below.
        resolved_inputs = context.get("_resolved_inputs", default=node.input_mapping)

        # Council path (SPEC-10): opt-in. A council node carries config["council"];
        # it deliberates and returns its own NodeResult — no single agent to run.
        council_cfg = node.config.get("council") if node.config else None
        if isinstance(council_cfg, dict):
            return await self._run_council(
                node=node,
                council_cfg=council_cfg,
                resolved_inputs=resolved_inputs,
                run_id=str(context.get("_run_id", default="")),
                start=start,
            )

        # Auction path (SPEC-09): opt-in. Engaged only when the node declares a
        # capability AND a selector is wired. On no candidates, falls through to
        # static ref_id resolution below (zero change for Node.agent DAGs).
        winning_bid: Bid | None = None
        cap_raw = node.config.get("capability") if node.config else None
        if cap_raw and self._agent_selector is not None:
            winning_bid = self._run_auction(
                node=node, capability_value=str(cap_raw), resolved_inputs=resolved_inputs
            )

        agent_name = str(winning_bid.agent_id) if winning_bid is not None else node.ref_id
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

        # Build goal from resolved inputs (read once above, shared with the auction)
        goal = self._build_goal(agent_name=agent_name, inputs=resolved_inputs)
        if goal is None:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Failed to build goal for agent '{agent_name}'",
            )

        # Populate global_memory from memory system if available.
        # context_warnings accumulates non-fatal failures in memory recall,
        # context compilation, and session ingest. The node still runs, but
        # the warnings surface in NodeResult.metadata so downstream consumers
        # (run_logger, eval pipeline, audit trail) can see when the agent ran
        # with degraded context — before this list existed, those failures were
        # logged-then-dropped and agents hallucinated on empty memory silently.
        context_warnings: list[dict[str, str]] = []
        run_id = str(context.get("_run_id", default=""))
        goal_text = str(resolved_inputs) if resolved_inputs else agent_name
        global_memory = await self._recall_global_memory(
            agent_name=agent_name,
            goal_text=goal_text,
            warnings=context_warnings,
        )

        # Compile context if compiler is available
        artifacts: dict[str, Any] = {}
        if self._context_compiler and self._token_budget:
            compiled = await self._compile_context(
                agent_name=agent_name,
                inputs=resolved_inputs,
                memories=global_memory,
                warnings=context_warnings,
            )
            if compiled:
                artifacts = {"compiled_context": compiled.to_messages()}

        # Build agent context
        agent_context = AgentContext(
            run_id=run_id,
            agent_id=agent_name,
            domain_context=self._domain_context,
            global_memory=global_memory,
            artifacts=artifacts,
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
                # context_output is the dict form for downstream node resolution
                context_output = self._extract_output_for_context(result=result)

                # Ingest successful result into session memory
                await self._ingest_result(
                    agent_name=agent_name,
                    output=output,
                    run_id=run_id,
                    warnings=context_warnings,
                )

                # Merge the agent's telemetry metadata (cost_estimate_usd,
                # tokens_total, model, etc.) into the NodeResult so downstream
                # BudgetGuard / online eval / run logger can see it. Our
                # framing keys (agent_id, context_hash) win on collision.
                merged_metadata: dict[str, Any] = dict(result.metadata or {})
                merged_metadata["agent_id"] = agent_name
                merged_metadata["context_hash"] = context_hash
                merged_metadata["_context_output"] = context_output
                if context_warnings:
                    merged_metadata["context_warnings"] = tuple(context_warnings)
                if winning_bid is not None:
                    merged_metadata["selection"] = winning_bid.to_metadata()
                return NodeResult(
                    node_id=node.id,
                    success=True,
                    output=output,
                    duration_ms=duration_ms,
                    metadata=merged_metadata,
                )
            else:
                return NodeResult(
                    node_id=node.id,
                    success=False,
                    error=result.error or f"Agent '{agent_name}' failed",
                    duration_ms=duration_ms,
                    metadata=self._failure_metadata(agent_name=agent_name, bid=winning_bid),
                )

        except Exception as e:
            duration_ms = (perf_counter() - start) * 1000
            logger.error("Agent '%s' raised exception: %s", agent_name, e, exc_info=True)
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                metadata=self._failure_metadata(agent_name=agent_name, bid=winning_bid),
            )

    def _build_goal(self, *, agent_name: str, inputs: dict[str, Any] | Any) -> BaseModel | None:
        """Build a goal model from resolved inputs.

        Filters out None values (unresolved optional $$refs$$) so Pydantic
        field defaults are used. This enables optional DAG nodes — if a node
        didn't run, its output_key won't be in context, the ref resolves to
        None, and the downstream goal uses its declared default value.
        """
        goal_type = self._registry.get_goal_type(agent_name=agent_name)
        if goal_type is None:
            return None

        if not isinstance(inputs, dict):
            return None

        # Drop None values so Pydantic uses field defaults for optional inputs
        filtered = {k: v for k, v in inputs.items() if v is not None}

        try:
            return goal_type(**filtered)
        except Exception as e:
            logger.warning("Failed to build goal for '%s': %s", agent_name, e)
            return None

    async def _run_council(
        self,
        *,
        node: Node,
        council_cfg: dict[str, Any],
        resolved_inputs: dict[str, Any] | Any,
        run_id: str,
        start: float,
    ) -> NodeResult:
        """Run a council node (SPEC-10): members deliberate, a vote decides, output = winner."""
        member_names = [str(m) for m in council_cfg.get("members", [])]
        options = tuple(str(o) for o in council_cfg.get("options", []))
        members: list[CouncilMember] = []
        for member_name in member_names:
            agent = self._registry.get(member_name)
            if isinstance(agent, CouncilMember):
                members.append(agent)
            else:
                logger.info("council node %s: member %r not a CouncilMember; skipped", node.id, member_name)

        if len(options) < 2 or not members:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"council node {node.id} needs >=2 options and >=1 CouncilMember",
                duration_ms=(perf_counter() - start) * 1000,
                metadata={"council": {"members": member_names, "options": list(options)}},
            )

        try:
            method = AggregationMethod(str(council_cfg.get("method", "majority")))
        except ValueError:
            method = AggregationMethod.MAJORITY
        config = CouncilConfig(method=method)
        aggregator = self._council_aggregator or DefaultVoteAggregator(config=config)
        council = AgentCouncil(members=tuple(members), aggregator=aggregator, config=config)
        question = CouncilQuestion(prompt=str(council_cfg.get("prompt", "")), options=options)

        agent_context = AgentContext(
            run_id=run_id,
            agent_id=f"council:{node.id}",
        )
        decision = await council.decide(question=question, goal=resolved_inputs, context=agent_context)
        return NodeResult(
            node_id=node.id,
            success=True,  # no-decision is a legitimate outcome, not a failure
            output=decision.winning_choice or "",
            duration_ms=(perf_counter() - start) * 1000,
            metadata={"council": decision.to_metadata()},
        )

    def _run_auction(
        self, *, node: Node, capability_value: str, resolved_inputs: dict[str, Any] | Any
    ) -> Bid | None:
        """Select an agent by auction (SPEC-09). None → caller falls through to static."""
        if self._agent_selector is None:
            return None
        try:
            capability = Capability(capability_value)
        except ValueError:
            logger.warning("auction: unknown capability %r on node %s", capability_value, node.id)
            return None
        candidates = self._registry.get_candidates(capability=capability)
        if not candidates:
            logger.info("auction: no candidates for %s on node %s", capability, node.id)
            return None
        bid_context = BidContext(
            capability=capability,
            goal_text=self._query_text_for(agent_name="", inputs=resolved_inputs),
            cost_utilization=self._budget_guard.cost_utilization if self._budget_guard else 0.0,
            token_utilization=self._budget_guard.token_utilization if self._budget_guard else 0.0,
        )
        bid = self._agent_selector.select(candidates=tuple(candidates), bid_context=bid_context)
        if bid is not None:
            logger.info("auction: node %s selected %s (score=%.3f)", node.id, bid.agent_id, bid.score)
        return bid

    @staticmethod
    def _failure_metadata(*, agent_name: str, bid: Bid | None) -> dict[str, Any]:
        """Failure NodeResult metadata — carries the selection bid for provenance if present."""
        meta: dict[str, Any] = {"agent_id": agent_name}
        if bid is not None:
            meta["selection"] = bid.to_metadata()
        return meta

    def _query_text_for(self, *, agent_name: str, inputs: dict[str, Any] | Any) -> str:
        """First populated well-known goal field in inputs; '' on miss."""
        if isinstance(inputs, dict):
            for key in ("objective", "goal", "description", "task", "query", "feature_description"):
                value = inputs.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return ""

    def _extract_output(self, *, result: AgentResult[Any]) -> str | None:
        """Extract serializable output string for NodeResult.output.

        NodeResult.output is a string consumed by tests, loggers, and the
        event payload 'output' field. It must remain JSON-stringified.
        """
        output = result.output
        if output is None:
            return None
        if hasattr(output, "model_dump"):
            return json.dumps(output.model_dump())
        return str(output)

    def _extract_output_for_context(self, *, result: AgentResult[Any]) -> Any | None:
        """Extract output for Context storage — dict form for Pydantic models.

        Returns model_dump() for Pydantic output so downstream nodes can do
        $$scrape_result.posts$$ via dot-path resolution. For non-Pydantic
        outputs (plain strings, already-dicts), returns None — signaling
        the executor should use result.output (the string) for context too.
        This preserves backward compat for existing CEMAF agents that return
        plain text while giving kyi's typed agents dict-form context.
        """
        output = result.output
        if output is None:
            return None
        if hasattr(output, "model_dump"):
            return output.model_dump()
        # Non-Pydantic: return None so executor falls back to result.output
        return None

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

    async def _recall_global_memory(
        self,
        *,
        agent_name: str,
        goal_text: str,
        warnings: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Load relevant memories for the agent; record any failure to `warnings`."""
        if self._memory_manager is None:
            return {}
        try:
            query_text = goal_text if goal_text else agent_name
            results = await self._memory_manager.recall(
                query=MemoryQuery(text=query_text, limit=10),
            )
            return {r.item.key: r.item.value for r in results}
        except Exception as exc:
            logger.warning("Failed to recall memory for '%s'", agent_name, exc_info=True)
            if warnings is not None:
                warnings.append(
                    {
                        "stage": "memory_recall",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
            return {}

    async def _compile_context(
        self,
        *,
        agent_name: str,
        inputs: dict[str, Any] | Any,
        memories: dict[str, Any],
        warnings: list[dict[str, str]] | None = None,
    ) -> CompiledContext | None:
        """Compile resolved inputs and memories into budgeted context; record failures."""
        if self._context_compiler is None or self._token_budget is None:
            return None
        try:
            artifact_pairs: list[tuple[str, str]] = []
            if isinstance(inputs, dict):
                for key, value in inputs.items():
                    artifact_pairs.append((key, str(value)))

            # Insert at index 0 so the preamble survives budget truncation.
            if self._blueprint_selector is not None:
                try:
                    query = self._query_text_for(agent_name=agent_name, inputs=inputs)
                    if query:
                        preamble = await self._blueprint_selector.select(query=query)
                        if preamble:
                            artifact_pairs.insert(0, ("blueprint:selected", preamble))
                except Exception as exc:
                    logger.warning(
                        "Blueprint selection failed for '%s'",
                        agent_name,
                        exc_info=True,
                    )
                    if warnings is not None:
                        warnings.append(
                            {
                                "stage": "blueprint_select",
                                "error_type": type(exc).__name__,
                                "error_message": str(exc),
                            }
                        )

            memory_pairs: list[tuple[str, str]] = []
            for key, value in memories.items():
                memory_pairs.append((f"memory:{key}", str(value)))

            return await self._context_compiler.compile(
                artifacts=tuple(artifact_pairs),
                memories=tuple(memory_pairs),
                budget=self._token_budget,
            )
        except Exception as exc:
            logger.warning(
                "Context compilation failed for '%s'",
                agent_name,
                exc_info=True,
            )
            if warnings is not None:
                warnings.append(
                    {
                        "stage": "context_compile",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
            return None

    async def _ingest_result(
        self,
        *,
        agent_name: str,
        output: str | None,
        run_id: str,
        warnings: list[dict[str, str]] | None = None,
    ) -> None:
        """Store agent result in session memory; record any failure to `warnings`."""
        if self._session_manager is None or not output:
            return
        try:
            await self._session_manager.ingest(
                session_id=run_id,
                key=f"{agent_name}_output",
                value={"output": output, "agent": agent_name},
            )
        except Exception as exc:
            logger.warning("Failed to ingest result for '%s'", agent_name, exc_info=True)
            if warnings is not None:
                warnings.append(
                    {
                        "stage": "session_ingest",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
