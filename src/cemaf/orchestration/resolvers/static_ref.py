"""StaticRefResolver — the trivial 'use node.ref_id' resolution. Always matches."""

from __future__ import annotations

from cemaf.orchestration.dag import Node
from cemaf.orchestration.resolvers.protocols import ResolveOutcome, RunAgent


class StaticRefResolver:
    """Returns ``RunAgent(node.ref_id)``. Always matches — registered last as the fallback.

    Empty ``ref_id`` is permitted at this layer (the executor handles the
    'no ref_id' error path uniformly, matching prior behaviour).
    """

    resolver_id: str = "static_ref"

    def matches(self, *, node: Node) -> bool:
        return True

    async def resolve(
        self, *, node: Node, resolved_inputs: object, run_id: str, start: float
    ) -> ResolveOutcome:
        return RunAgent(agent_name=node.ref_id)
