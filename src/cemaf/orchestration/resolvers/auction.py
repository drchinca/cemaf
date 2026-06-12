"""AuctionResolver — extracts the SPEC-09 auction branch from execute_node.

Matches a node iff ``config["capability"]`` is set AND an ``AgentSelector`` is
wired. On no candidates / unknown capability, falls through to ``node.ref_id``
(via ``RunAgent``) so a static-fallback DAG still works exactly as before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cemaf.agents.selection import AgentSelector, Bid, BidContext, Capability
from cemaf.orchestration.dag import Node
from cemaf.orchestration.resolvers.protocols import ResolveOutcome, RunAgent

if TYPE_CHECKING:  # only used for type hints, avoids a runtime import
    from cemaf.agents.registry import AgentRegistry
    from cemaf.observability.budget_guard import BudgetGuard

logger = logging.getLogger(__name__)


def _query_text(*, inputs: object) -> str:
    """First populated well-known goal field in inputs; '' on miss."""
    if isinstance(inputs, dict):
        for key in ("objective", "goal", "description", "task", "query", "feature_description"):
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


class AuctionResolver:
    """Selects an agent by SPEC-09 auction; falls through to ref_id on miss."""

    resolver_id: str = "auction"

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        selector: AgentSelector,
        budget_guard: BudgetGuard | None = None,
    ) -> None:
        self._registry = registry
        self._selector = selector
        self._budget_guard = budget_guard

    def matches(self, *, node: Node) -> bool:
        return bool(node.config and node.config.get("capability"))

    async def resolve(
        self, *, node: Node, resolved_inputs: object, run_id: str, start: float
    ) -> ResolveOutcome:
        capability_value = str((node.config or {}).get("capability", ""))
        bid = self._auction(node=node, capability_value=capability_value, resolved_inputs=resolved_inputs)
        if bid is None:
            # No candidates / unknown capability → fall through to the static ref_id path.
            return RunAgent(agent_name=node.ref_id)
        return RunAgent(agent_name=str(bid.agent_id), bid_metadata=bid.to_metadata())

    def _auction(self, *, node: Node, capability_value: str, resolved_inputs: object) -> Bid | None:
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
            goal_text=_query_text(inputs=resolved_inputs),
            cost_utilization=self._budget_guard.cost_utilization if self._budget_guard else 0.0,
            token_utilization=self._budget_guard.token_utilization if self._budget_guard else 0.0,
        )
        bid = self._selector.select(candidates=tuple(candidates), bid_context=bid_context)
        if bid is not None:
            logger.info("auction: node %s selected %s (score=%.3f)", node.id, bid.agent_id, bid.score)
        return bid
