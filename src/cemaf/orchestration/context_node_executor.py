"""ContextNodeExecutor - Bridges DAG nodes to agents via registry."""

import asyncio
import dataclasses
import hashlib
import json
import logging
import math
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult
from cemaf.agents.protocols import Agent
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import AgentSelector
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, ContextCompiler
from cemaf.context.context import Context
from cemaf.core.domain import DomainContext
from cemaf.core.enums import MemoryScope
from cemaf.core.provenance import ProvenanceLink, SourceReference
from cemaf.core.types import JSON, AgentID, NodeID, ProvenanceID
from cemaf.core.utils import utc_now
from cemaf.council.protocols import VoteAggregator
from cemaf.interceptors.pipeline import InterceptorPipeline
from cemaf.interceptors.types import (
    MAX_VISIBLE_HINTS,
    RECOVERY_HINTS_KEY,
    DecisionKind,
    PostflightDecision,
    RecoveryHint,
)
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
from cemaf.orchestration.resolvers import (
    AuctionResolver,
    CouncilResolver,
    NodeComplete,
    NodeResolver,
    ResolveOutcome,
    RunAgent,
    StaticRefResolver,
)
from cemaf.retrieval.protocols import VectorStore

logger = logging.getLogger(__name__)


def _failure_metadata(*, agent_name: str, bid_metadata: JSON | None) -> dict[str, Any]:
    """Failure NodeResult metadata — carries the selection bid for provenance if present."""
    meta: dict[str, Any] = {"agent_id": agent_name}
    if bid_metadata is not None:
        meta["selection"] = bid_metadata
    return meta


def _apply_recovery_exhausted(
    *, result: NodeResult, decision: PostflightDecision, attempts: int
) -> NodeResult:
    """Downgrade a RECOVER request to a REJECT once the recovery budget is spent.

    Mirrors the pipeline's ``_apply_reject`` shape (gate_rejected stamped so the
    outer ``_execute_with_retry`` does not re-run a deterministic gate failure)
    while preserving the recovery trail in metadata for provenance.
    """

    block = dict(result.metadata.get("interceptors", {})) if result.metadata else {}
    if not isinstance(block, dict):
        block = {}
    hint = decision.recovery_hint
    block["rejected_by"] = decision.interceptor_id
    block["reason"] = f"recovery exhausted after {attempts} attempt(s): {decision.reason or 'no reason'}"
    block["rejected_output"] = result.output
    block["gate_rejected"] = True
    block["recovery_exhausted"] = True
    block["recovery_attempts"] = attempts
    if hint is not None:
        block["last_recovery_hint"] = hint.to_dict()
    new_metadata = {**(result.metadata or {}), "interceptors": block}
    return dataclasses.replace(
        result,
        success=False,
        output=None,
        error=f"interceptor {decision.interceptor_id} rejected node after {attempts} recovery attempt(s)",
        metadata=new_metadata,
    )


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
        interceptor_pipeline: InterceptorPipeline | None = None,
        max_recovery_attempts: int = 2,
    ) -> None:
        """Initialize with registry and optional compiler/budget for context compilation.

        ``max_recovery_attempts`` (SPEC-01a + RECOVER extension) caps how many times
        a POST interceptor can ask the executor to re-run the same node with a
        feedback hint before the result is treated as REJECT. 0 disables recovery
        (any RECOVER decision is treated as REJECT immediately).
        """
        if max_recovery_attempts < 0:
            raise ValueError("max_recovery_attempts must be >= 0")
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
        self._interceptor_pipeline = interceptor_pipeline
        self._max_recovery_attempts = max_recovery_attempts

        # NodeResolver chain — first match wins, registered most-specific first.
        # Council short-circuits with its own NodeResult; AuctionResolver picks an
        # agent (or falls through to ref_id); StaticRefResolver is the universal
        # fallback. When agent_selector is absent, auction is skipped — preserves
        # the prior "static unless a selector is wired" semantics.
        resolvers: list[NodeResolver] = [
            CouncilResolver(registry=agent_registry, aggregator=council_aggregator),
        ]
        if agent_selector is not None:
            resolvers.append(
                AuctionResolver(
                    registry=agent_registry,
                    selector=agent_selector,
                    budget_guard=budget_guard,
                )
            )
        resolvers.append(StaticRefResolver())
        self._resolvers: tuple[NodeResolver, ...] = tuple(resolvers)

    async def execute_node(
        self,
        node: Node,
        context: Context,
    ) -> NodeResult:
        """Execute a single node by dispatching to the appropriate agent."""
        start = perf_counter()

        # Resolved inputs (post $$ref$$ resolution) — read once, shared by resolvers
        # (for an auction's goal_text) and the goal builder below.
        resolved_inputs = context.get("_resolved_inputs", default=node.input_mapping)
        run_id_value = str(context.get("_run_id", default=""))

        # NodeResolver dispatch — replaces the bespoke council / auction / static
        # if-branches. First resolver whose matches() returns True wins; council
        # short-circuits with its own NodeResult, auction picks an agent (or falls
        # through to ref_id), static returns ref_id. The executor never grows a
        # branch when a new node kind is added — register a new resolver instead.
        outcome = await self._resolve_node(
            node=node, resolved_inputs=resolved_inputs, run_id=run_id_value, start=start
        )
        if isinstance(outcome, NodeComplete):
            return outcome.result
        bid_metadata = outcome.bid_metadata
        agent_name = outcome.agent_name
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
            run_id=run_id,
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

        # PRE interceptor chain (SPEC-01a). Runs on the already-built AgentContext;
        # may enrich it (model_copy) or REJECT (skip the agent). Empty/None = no-op.
        if self._interceptor_pipeline is not None and not self._interceptor_pipeline.is_empty:
            agent_context, pre_reject = await self._interceptor_pipeline.run_pre(
                node=node, context=agent_context
            )
            if pre_reject is not None:
                return NodeResult(
                    node_id=node.id,
                    success=False,
                    error=f"interceptor {pre_reject.interceptor_id} rejected node: {pre_reject.reason}",
                    duration_ms=(perf_counter() - start) * 1000,
                    metadata={
                        "agent_id": agent_name,
                        "interceptors": {
                            "rejected_by": pre_reject.interceptor_id,
                            "reason": pre_reject.reason,
                            "phase": "pre",
                            "gate_rejected": True,
                        },
                    },
                )

        # Compute context hash for provenance
        context_hash = self._compute_context_hash(inputs=resolved_inputs)

        # Recovery loop (SPEC-01a + RECOVER): a POST interceptor may ask the
        # executor to re-run the agent with a feedback hint. Bounded by
        # max_recovery_attempts; hints accumulate across attempts so the agent
        # sees prior failures.
        recovery_hints: list[RecoveryHint] = []
        attempts_remaining = self._max_recovery_attempts
        attempt_usage: list[dict[str, float | int]] = []
        accumulated_cost_usd = 0.0
        accumulated_tokens = 0

        try:
            while True:
                # Inject accumulated recovery hints into agent_context for THIS attempt.
                # Show only the LAST MAX_VISIBLE_HINTS — keeps token cost bounded and
                # ensures the freshest feedback wins when an agent has limited attention.
                attempt_context = (
                    agent_context.model_copy(
                        update={
                            "global_memory": {
                                **agent_context.global_memory,
                                RECOVERY_HINTS_KEY: [
                                    h.to_dict() for h in recovery_hints[-MAX_VISIBLE_HINTS:]
                                ],
                            }
                        }
                    )
                    if recovery_hints
                    else agent_context
                )

                result = await agent.run(goal=goal, context=attempt_context)
                duration_ms = (perf_counter() - start) * 1000

                # Preserve the bill for every agent attempt, including drafts
                # rejected by a POST gate. The outer DAG budget guard sees only
                # the final NodeResult, so returning final-attempt telemetry
                # alone silently under-counts recovery work.
                result_metadata = result.metadata or {}
                usage_keys_present = any(
                    key in result_metadata
                    for key in ("cost_estimate_usd", "cost_usd", "tokens_total", "tokens_used")
                )
                if usage_keys_present:
                    try:
                        attempt_cost = float(
                            result_metadata.get("cost_estimate_usd", result_metadata.get("cost_usd", 0.0))
                            or 0.0
                        )
                        attempt_tokens = int(
                            result_metadata.get("tokens_total", result_metadata.get("tokens_used", 0)) or 0
                        )
                    except (TypeError, ValueError):
                        attempt_cost, attempt_tokens = 0.0, 0
                    if math.isnan(attempt_cost) or math.isinf(attempt_cost):
                        attempt_cost = 0.0
                    accumulated_cost_usd += max(0.0, attempt_cost)
                    accumulated_tokens += max(0, attempt_tokens)
                    attempt_usage.append(
                        {
                            "attempt": len(attempt_usage) + 1,
                            "cost_usd": max(0.0, attempt_cost),
                            "tokens": max(0, attempt_tokens),
                        }
                    )

                # Build provenance link (recorded once per attempt for an honest trail)
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

                if not result.success:
                    failure_metadata = _failure_metadata(agent_name=agent_name, bid_metadata=bid_metadata)
                    if attempt_usage:
                        failure_metadata.update(
                            {
                                "cost_estimate_usd": accumulated_cost_usd,
                                "tokens_total": accumulated_tokens,
                                "attempt_usage": attempt_usage,
                            }
                        )
                    return NodeResult(
                        node_id=node.id,
                        success=False,
                        error=result.error or f"Agent '{agent_name}' failed",
                        duration_ms=duration_ms,
                        metadata=failure_metadata,
                    )

                output = self._extract_output(result=result)
                # context_output is the dict form for downstream node resolution
                context_output = self._extract_output_for_context(result=result)

                # Merge the agent's telemetry metadata (cost_estimate_usd,
                # tokens_total, model, etc.) into the NodeResult so downstream
                # BudgetGuard / online eval / run logger can see it. Our
                # framing keys (agent_id, context_hash) win on collision.
                merged_metadata: dict[str, Any] = dict(result.metadata or {})
                merged_metadata["agent_id"] = agent_name
                merged_metadata["context_hash"] = context_hash
                merged_metadata["_context_output"] = context_output
                merged_metadata["recalled_memory_count"] = len(global_memory)
                if attempt_usage:
                    merged_metadata["cost_estimate_usd"] = accumulated_cost_usd
                    merged_metadata["tokens_total"] = accumulated_tokens
                    merged_metadata["attempt_usage"] = attempt_usage
                if context_warnings:
                    merged_metadata["context_warnings"] = tuple(context_warnings)
                if bid_metadata is not None:
                    merged_metadata["selection"] = bid_metadata
                if recovery_hints:
                    merged_metadata["recovery_attempts"] = len(recovery_hints)
                success_result = NodeResult(
                    node_id=node.id,
                    success=True,
                    output=output,
                    duration_ms=duration_ms,
                    metadata=merged_metadata,
                )

                # POST interceptor chain (SPEC-01a). Runs only on a successful
                # NodeResult; may REJECT (flip to failure + gate_rejected) or
                # RECOVER (re-run the agent with a hint). Empty/None = no-op.
                if self._interceptor_pipeline is None or self._interceptor_pipeline.is_empty:
                    return success_result

                success_result, post_decision = await self._interceptor_pipeline.run_post(
                    node=node, context=attempt_context, result=success_result
                )

                if (
                    post_decision is not None
                    and post_decision.kind is DecisionKind.RECOVER
                    and post_decision.recovery_hint is not None
                    and attempts_remaining > 0
                ):
                    recovery_hints.append(post_decision.recovery_hint)
                    attempts_remaining -= 1
                    logger.info(
                        "node %s: POST RECOVER from %s (%s); retrying with hint (%d remaining)",
                        node.id,
                        post_decision.interceptor_id,
                        post_decision.recovery_hint.code,
                        attempts_remaining,
                    )
                    continue

                if post_decision is not None and post_decision.kind is DecisionKind.RECOVER:
                    # RECOVER requested but budget exhausted (or recovery disabled) —
                    # downgrade to REJECT so downstream blocks and gate_rejected stamps.
                    return _apply_recovery_exhausted(
                        result=success_result,
                        decision=post_decision,
                        attempts=len(recovery_hints),
                    )

                return success_result

        except Exception as e:
            duration_ms = (perf_counter() - start) * 1000
            logger.error("Agent '%s' raised exception: %s", agent_name, e, exc_info=True)
            crash_metadata = _failure_metadata(agent_name=agent_name, bid_metadata=bid_metadata)
            # Preserve the recovery trail when an agent crashes mid-loop — without
            # this, ops lose the diagnostic record of which hints were tried before
            # the crash. The interceptors block keeps the same shape used elsewhere.
            if recovery_hints:
                crash_metadata["recovery_attempts"] = len(recovery_hints)
                crash_metadata["recovery_hints_trail"] = [h.to_dict() for h in recovery_hints]
            if attempt_usage:
                crash_metadata.update(
                    {
                        "cost_estimate_usd": accumulated_cost_usd,
                        "tokens_total": accumulated_tokens,
                        "attempt_usage": attempt_usage,
                    }
                )
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                metadata=crash_metadata,
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

    async def _resolve_node(
        self,
        *,
        node: Node,
        resolved_inputs: dict[str, Any] | Any,
        run_id: str,
        start: float,
    ) -> ResolveOutcome:
        """Dispatch via the NodeResolver chain — first matching resolver wins.

        Replaces the bespoke council / auction / static if-branches with one
        uniform seam. Adding a new node kind = registering a new resolver.
        """
        for resolver in self._resolvers:
            if resolver.matches(node=node):
                return await resolver.resolve(
                    node=node, resolved_inputs=resolved_inputs, run_id=run_id, start=start
                )
        # StaticRefResolver always matches → unreachable in practice, but keep an
        # explicit fallback so a misconfigured chain fails closed instead of NoneType.
        return RunAgent(agent_name=node.ref_id)

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
        run_id: str,
        warnings: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Load relevant memories for the agent; record any failure to `warnings`."""
        if self._memory_manager is None:
            return {}
        try:
            query_text = goal_text if goal_text else agent_name
            durable_scopes = tuple(scope for scope in MemoryScope if scope is not MemoryScope.SESSION)
            durable_results, session_results = await asyncio.gather(
                self._memory_manager.recall(
                    query=MemoryQuery(text=query_text, scopes=durable_scopes, limit=10),
                ),
                self._memory_manager.recall(
                    query=MemoryQuery(
                        text=query_text,
                        scope=MemoryScope.SESSION,
                        limit=10,
                        session_id=run_id,
                    ),
                ),
            )
            recalled: dict[str, Any] = {}
            for result in (*durable_results, *session_results):
                recalled[result.item.key] = result.item.value
            return recalled
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
