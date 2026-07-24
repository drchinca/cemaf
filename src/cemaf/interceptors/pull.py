"""PullInterceptor — first real PreInterceptor; pull-not-push context retrieval.

Adapts SPEC-02's PullInterceptor (which targets un-landed NodeInterceptor/
DAGNode/Goal/TaskContext/Context.surfaced_sources) to the landed SPEC-01a
PreInterceptor contract: `pre(*, node: Node, context: AgentContext)`. Key
substitutions:
  - "goal.text" -> f"{node.name} {node.description}" (Node has no `goal`
    field; name+description is always populated, no extra caller config
    required).
  - "node.budget.pull_tokens" -> this interceptor's own `pull_tokens`
    constructor config (Node has no `budget` field).
  - "ctx.surfaced_sources" -> AgentContext.artifacts["surfaced_sources"], a
    tuple[CiteableChunk, ...], set via PreflightDecision.enriched_context
    (AgentContext.model_copy) exactly like ContextNodeExecutor already
    populates artifacts["compiled_context"].
  - "node.grounding == GroundingPolicy.REQUIRED" -> `grounding_required_nodes`
    constructor config naming node ids by string (no such field on Node).
  - SPEC-02 Inv 13 (meta-recovery patch union via ctx.pending_meta_patches) is
    OUT OF SCOPE — SPEC-06 doesn't exist; there is no patch source to union.

Token-budget reconciliation: ``CompiledContext.to_messages()`` (what
ContextNodeExecutor puts in ``artifacts["compiled_context"]``) discards
``total_tokens``, so ContextNodeExecutor separately stashes it under
``artifacts["compiled_context_tokens"]``. When this interceptor is built with
a ``token_budget``, it reads that sibling key and caps its own contribution at
``token_budget.available_tokens - compiled_context_tokens`` (floored at 0) —
so ``surfaced_sources`` plus the already-compiled context can never together
exceed the real model window. Without ``token_budget`` configured, behavior is
unchanged: this interceptor budgets blind against ``pull_tokens`` alone, same
as before.

Deliberately does NOT pull `context.global_memory` into `surfaced_sources`.
`ContextNodeExecutor` already recalls memory into `global_memory` before this
interceptor runs — re-wrapping the same items as CiteableChunks here would
surface identical content twice, through two different priority systems, with
no reconciliation. Memory stays exactly where it already is.
See docs/architecture/roadmap-plan.md Phase 5.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

from cemaf.agents.base import AgentContext
from cemaf.citation.models import Citation
from cemaf.context.budget import TokenBudget
from cemaf.datasources.models import (
    CiteableChunk,
    DataSourceCapability,
    EntityRef,
    HealthStatus,
    RetrievalQuery,
    SourceKind,
)
from cemaf.datasources.protocols import DataSource, EntityExtractor
from cemaf.datasources.registry import DataSourceRegistry
from cemaf.interceptors.types import DecisionKind, PreflightDecision
from cemaf.knowledge.models import RelationType
from cemaf.knowledge.protocols import KnowledgeGraph
from cemaf.orchestration.dag import Node

logger = logging.getLogger(__name__)


class PullInterceptor:
    """PRE interceptor: pull context from KG + DataSources before agent.run().

    ``node_pattern`` is the node id this applies to, or "*" for all AGENT
    nodes. A node that does not match is passed through (ACCEPT, no
    enrichment). Registration order in InterceptorPipeline is run order —
    there is no phase/position enum in the shipped pipeline to declare.
    """

    def __init__(
        self,
        *,
        pull_tokens: int,
        knowledge_graph: KnowledgeGraph | None = None,
        data_source_registry: DataSourceRegistry | None = None,
        entity_extractor: EntityExtractor | None = None,
        source_weights: Mapping[str, float] | None = None,
        node_pattern: str = "*",
        grounding_required_nodes: frozenset[str] = frozenset(),
        interceptor_id: str = "pull",
        relation_type: RelationType | None = None,
        kg_depth: int = 1,
        timeout_ms: int = 3_000,
        token_budget: TokenBudget | None = None,
    ) -> None:
        if pull_tokens <= 0:
            raise ValueError("pull_tokens must be positive")
        if source_weights is not None and sum(source_weights.values()) > 1.0:
            raise ValueError("source_weights must sum to <= 1.0")
        self._pull_tokens = pull_tokens
        self._knowledge_graph = knowledge_graph
        self._registry = data_source_registry
        self._entity_extractor = entity_extractor
        self._source_weights = dict(source_weights) if source_weights else None
        self._pattern = node_pattern
        self._grounding_required_nodes = grounding_required_nodes
        self._id = interceptor_id
        self._relation_type = relation_type
        self._kg_depth = kg_depth
        self._timeout_s = timeout_ms / 1000
        self._token_budget = token_budget

    def _effective_pull_tokens(self, context: AgentContext) -> int:
        """Cap pull_tokens against what compiled_context already spent, when a
        real model-window token_budget is configured. Without it, unchanged."""
        if self._token_budget is None:
            return self._pull_tokens
        compiled_context_tokens = int(context.artifacts.get("compiled_context_tokens", 0))
        remaining = self._token_budget.available_tokens - compiled_context_tokens
        return max(0, min(self._pull_tokens, remaining))

    @property
    def interceptor_id(self) -> str:
        return self._id

    def _matches(self, node: Node) -> bool:
        return self._pattern == "*" or self._pattern == str(node.id)

    async def pre(self, *, node: Node, context: AgentContext) -> PreflightDecision:
        if not self._matches(node):
            return PreflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self._id)

        goal_text = f"{node.name} {node.description}".strip()
        entities = self._entity_extractor.extract(text=goal_text) if self._entity_extractor else ()
        effective_pull_tokens = self._effective_pull_tokens(context)

        candidates: list[CiteableChunk] = []
        candidates.extend(await self._pull_kg(entities))
        candidates.extend(
            await self._pull_data_sources(
                goal_text=goal_text, entities=entities, pull_tokens=effective_pull_tokens
            )
        )

        surfaced = self._merge_and_evict(candidates, pull_tokens=effective_pull_tokens)

        if not surfaced and str(node.id) in self._grounding_required_nodes:
            return PreflightDecision(
                kind=DecisionKind.REJECT,
                interceptor_id=self._id,
                reason="no_grounding_available",
            )

        enriched = context.model_copy(
            update={"artifacts": {**context.artifacts, "surfaced_sources": surfaced}}
        )
        return PreflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self._id, enriched_context=enriched)

    async def _pull_kg(self, entities: tuple[EntityRef, ...]) -> list[CiteableChunk]:
        if self._knowledge_graph is None or not entities:
            return []
        chunks: list[CiteableChunk] = []
        for entity in entities:
            try:
                result = await self._knowledge_graph.query_neighbors(
                    entity.id, relation_type=self._relation_type, depth=self._kg_depth
                )
            except Exception as exc:  # noqa: BLE001 — contain, one bad entity shouldn't sink the pull
                logger.warning("kg.query_failed entity=%s error=%s", entity.id, exc)
                continue
            for relation in result.relations:
                citation = Citation(
                    id=f"kg:{relation.source_id}:{relation.target_id}",
                    source_id=SourceKind.KG,
                    source_type="knowledge_graph",
                    section=relation.target_id,
                    quote=relation.type.value,
                )
                chunks.append(
                    CiteableChunk(
                        chunk_id=f"kg:{relation.source_id}:{relation.target_id}:{relation.type.value}",
                        content=f"{relation.source_id} {relation.type.value} {relation.target_id}",
                        citation=citation,
                        token_count=max(1, len(relation.type.value) // 4 + len(relation.target_id) // 4),
                        source_kind=SourceKind.KG,
                    )
                )
        return chunks

    async def _pull_data_sources(
        self, *, goal_text: str, entities: tuple[EntityRef, ...], pull_tokens: int
    ) -> list[CiteableChunk]:
        if self._registry is None or pull_tokens <= 0:
            return []
        capable = self._registry.list_capable(DataSourceCapability.SEARCH)
        if not capable:
            return []

        healthy: list[DataSource] = []
        for source in capable:
            try:
                status = await source.health()
            except Exception:  # noqa: BLE001 — an unhealthy check result, not a fatal error
                status = HealthStatus.UNHEALTHY
            if status is HealthStatus.UNHEALTHY:
                logger.info("datasource.skipped_unhealthy source_id=%s", source.source_id)
                continue
            healthy.append(source)
        if not healthy:
            return []

        sub_budgets = self._compute_sub_budgets(healthy, pull_tokens=pull_tokens)
        query = RetrievalQuery(
            text=goal_text, entities=entities, top_k=8, timeout_ms=int(self._timeout_s * 1000)
        )
        results = await asyncio.gather(
            *(
                self._retrieve_with_timeout(source=source, query=query, budget=sub_budgets[source.source_id])
                for source in healthy
            )
        )
        chunks: list[CiteableChunk] = []
        for outcome in results:
            chunks.extend(outcome)
        return chunks

    async def _retrieve_with_timeout(
        self, *, source: DataSource, query: RetrievalQuery, budget: TokenBudget
    ) -> tuple[CiteableChunk, ...]:
        try:
            return await asyncio.wait_for(
                source.retrieve(query=query, budget=budget), timeout=self._timeout_s
            )
        except TimeoutError:
            logger.warning("datasource.timeout source_id=%s", source.source_id)
            return ()
        except Exception as exc:  # noqa: BLE001 — one failing source shouldn't sink the whole pull
            logger.warning("datasource.retrieve_failed source_id=%s error=%s", source.source_id, exc)
            return ()

    def _compute_sub_budgets(self, sources: list[DataSource], *, pull_tokens: int) -> dict[str, TokenBudget]:
        ordered = sorted(sources, key=lambda s: s.source_id)
        if self._source_weights:
            return {
                source.source_id: TokenBudget(
                    max_tokens=int(pull_tokens * self._source_weights.get(source.source_id, 0.0))
                )
                for source in ordered
            }
        base = pull_tokens // len(ordered)
        remainder = pull_tokens - base * len(ordered)
        budgets: dict[str, TokenBudget] = {}
        for index, source in enumerate(ordered):
            tokens = base + (remainder if index == 0 else 0)
            budgets[source.source_id] = TokenBudget(max_tokens=tokens)
        return budgets

    def _merge_and_evict(
        self, candidates: list[CiteableChunk], *, pull_tokens: int
    ) -> tuple[CiteableChunk, ...]:
        ordered = sorted(
            candidates,
            key=lambda c: (-c.effective_priority, -c.confidence, c.retrieved_at, c.chunk_id),
        )
        surfaced: list[CiteableChunk] = []
        running_total = 0
        for chunk in ordered:
            if running_total + chunk.token_count > pull_tokens:
                logger.info("pull.evicted chunk_id=%s reason=over_budget", chunk.chunk_id)
                break
            surfaced.append(chunk)
            running_total += chunk.token_count
        return tuple(surfaced)
