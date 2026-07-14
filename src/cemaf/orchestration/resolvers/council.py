"""CouncilResolver — extracts the SPEC-10 council branch from execute_node.

A council node carries ``config["council"]``; the resolver runs the
deliberation and returns ``NodeComplete`` with the verdict as
``NodeResult.output`` (so a downstream JSON_RULE edge can route on it).
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

from cemaf.agents.base import AgentContext
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.council import AgentCouncil
from cemaf.council.protocols import CouncilMember, VoteAggregator
from cemaf.council.types import AggregationMethod, CouncilConfig, CouncilQuestion
from cemaf.orchestration.dag import Node
from cemaf.orchestration.resolvers.protocols import NodeComplete, ResolveOutcome
from cemaf.orchestration.results import NodeResult

if TYPE_CHECKING:
    from cemaf.agents.registry import AgentRegistry
    from cemaf.knowledge.protocols import KnowledgeGraph
else:
    type KnowledgeGraph = Any

logger = logging.getLogger(__name__)


class CouncilResolver:
    """Runs a council node end-to-end; returns a NodeComplete with the verdict."""

    resolver_id: str = "council"

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        aggregator: VoteAggregator | None = None,
        knowledge_graph: KnowledgeGraph | None = None,
    ) -> None:
        self._registry = registry
        self._aggregator = aggregator
        self._knowledge_graph = knowledge_graph

    def matches(self, *, node: Node) -> bool:
        return bool(node.config and isinstance(node.config.get("council"), dict))

    async def resolve(
        self, *, node: Node, resolved_inputs: object, run_id: str, start: float
    ) -> ResolveOutcome:
        council_cfg: dict[str, Any] = node.config["council"]
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
            return NodeComplete(
                result=NodeResult(
                    node_id=node.id,
                    success=False,
                    error=f"council node {node.id} needs >=2 options and >=1 CouncilMember",
                    duration_ms=(perf_counter() - start) * 1000,
                    metadata={"council": {"members": member_names, "options": list(options)}},
                )
            )

        try:
            method = AggregationMethod(str(council_cfg.get("method", "majority")))
        except ValueError:
            method = AggregationMethod.MAJORITY
        # rounds defaults to 1 (single-round ensemble) — preserves prior behaviour
        # for any council node authored before the multi-round primitive landed.
        rounds_raw = council_cfg.get("rounds", 1)
        try:
            rounds = max(1, int(rounds_raw))
        except (TypeError, ValueError):
            rounds = 1
        config = CouncilConfig(method=method, rounds=rounds)
        # A wired council_aggregator (BYO-X) governs aggregation with its OWN policy —
        # the node's `method` only configures the default aggregator. (The shared config
        # still bounds member concurrency/timeout in either case.)
        aggregator = self._aggregator or DefaultVoteAggregator(config=config)
        council = AgentCouncil(members=tuple(members), aggregator=aggregator, config=config)
        question = CouncilQuestion(prompt=str(council_cfg.get("prompt", "")), options=options)

        agent_context = AgentContext(
            run_id=run_id,
            agent_id=f"council:{node.id}",
            knowledge_graph=self._knowledge_graph,
        )
        decision = await council.decide(question=question, goal=resolved_inputs, context=agent_context)
        return NodeComplete(
            result=NodeResult(
                node_id=node.id,
                success=True,  # no-decision is a legitimate outcome, not a failure
                output=decision.winning_choice or "",
                duration_ms=(perf_counter() - start) * 1000,
                metadata={"council": decision.to_metadata()},
            )
        )
