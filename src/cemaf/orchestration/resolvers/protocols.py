"""NodeResolver protocol + outcome value types — the dispatch seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.orchestration.dag import Node
from cemaf.orchestration.results import NodeResult


@dataclass(frozen=True, slots=True)
class RunAgent:
    """The executor should resolve and run ``agent_name``.

    ``bid_metadata`` (e.g. an auction Bid projection) is merged into
    ``NodeResult.metadata`` on success/failure for provenance — None when no
    selection took place (static ref path).
    """

    agent_name: str
    bid_metadata: JSON | None = None


@dataclass(frozen=True, slots=True)
class NodeComplete:
    """The resolver fully handled the node and produced its own ``NodeResult``.

    The executor returns this result as-is (no agent.run, no POST chain — the
    resolver's output is canonical, e.g. a council verdict).
    """

    result: NodeResult


ResolveOutcome = RunAgent | NodeComplete


@runtime_checkable
class NodeResolver(Protocol):
    """A resolver claims a node and decides the next step.

    Registered in order; the first resolver whose ``matches(node)`` returns True
    wins. ``resolve`` is async because a NodeComplete resolver may need to run
    real work (a council deliberation, for example).
    """

    @property
    def resolver_id(self) -> str: ...

    def matches(self, *, node: Node) -> bool: ...

    async def resolve(
        self, *, node: Node, resolved_inputs: object, run_id: str, start: float
    ) -> ResolveOutcome: ...
