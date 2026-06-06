"""Protocols for the agent council (SPEC-10 §2)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cemaf.agents.base import AgentContext
from cemaf.core.types import AgentID
from cemaf.council.types import CouncilDecision, CouncilQuestion, Opinion


@runtime_checkable
class CouncilMember(Protocol):
    """Produces an Opinion on a question. Distinguished from a plain Agent by `deliberate`."""

    @property
    def id(self) -> AgentID: ...

    async def deliberate[GoalT](
        self, *, question: CouncilQuestion, goal: GoalT, context: AgentContext
    ) -> Opinion: ...


@runtime_checkable
class VoteAggregator(Protocol):
    """BYO-X seam — combine opinions into a decision. Pure, deterministic, no I/O."""

    def aggregate(self, *, question: CouncilQuestion, opinions: tuple[Opinion, ...]) -> CouncilDecision: ...
