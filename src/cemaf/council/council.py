"""AgentCouncil — runs members concurrently, aggregates, records provenance (SPEC-10)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from cemaf.agents.base import AgentContext
from cemaf.agents.protocols import Agent
from cemaf.core.types import AgentID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.protocols import CouncilMember, VoteAggregator
from cemaf.council.types import CouncilConfig, CouncilDecision, CouncilQuestion, Opinion

logger = logging.getLogger(__name__)


class AgentCouncil:
    """Runs members concurrently (bounded + timed), aggregates, records provenance."""

    def __init__(
        self,
        *,
        members: tuple[CouncilMember, ...],
        aggregator: VoteAggregator,
        config: CouncilConfig | None = None,
    ) -> None:
        self._members = members
        self._aggregator = aggregator
        self._config = config or CouncilConfig()

    async def decide[GoalT](
        self, *, question: CouncilQuestion, goal: GoalT, context: AgentContext
    ) -> CouncilDecision:
        semaphore = asyncio.Semaphore(self._config.max_concurrency)
        timeout_s = self._config.member_timeout.total_seconds()

        async def run_member(member: CouncilMember) -> Opinion:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        member.deliberate(question=question, goal=goal, context=context),
                        timeout=timeout_s,
                    )
                except asyncio.CancelledError:
                    # CancelledError is BaseException in 3.13+ (so `except Exception` would
                    # already skip it); the explicit re-raise documents intent and keeps
                    # behaviour identical on 3.8–3.12 where it was an Exception.
                    raise
                except TimeoutError as exc:
                    logger.info("council member %s timed out, abstaining", member.id)
                    return Opinion(
                        member_id=member.id,
                        choice=None,
                        confidence=0.0,
                        abstained=True,
                        rationale=f"timeout: {exc!r}",
                    )
                except Exception as exc:  # noqa: BLE001 — abstain, don't crash
                    # A raise here may be a legitimate decline OR a real bug in member
                    # code. Log at WARNING (not INFO) so genuine bugs surface in ops,
                    # and keep the repr on the ballot so provenance is distinguishable.
                    logger.warning(
                        "council member %s raised %s, abstaining: %r",
                        member.id,
                        type(exc).__name__,
                        exc,
                    )
                    return Opinion(
                        member_id=member.id,
                        choice=None,
                        confidence=0.0,
                        abstained=True,
                        rationale=f"{type(exc).__name__}: {exc!r}",
                    )

        opinions = await asyncio.gather(*(run_member(m) for m in self._members))
        return self._aggregator.aggregate(question=question, opinions=tuple(opinions))


class _AgentMemberAdapter:
    """Wraps a plain Agent as a CouncilMember.

    Runs `agent.run(goal)`, maps `AgentResult.output` → choice via `extract_choice`.
    The agent fails, raises, or maps outside `question.options` → abstention.
    """

    def __init__(
        self,
        *,
        agent: Agent[Any, Any],
        extract_choice: Callable[[Any], str],
    ) -> None:
        self._agent = agent
        self._extract = extract_choice

    @property
    def id(self) -> AgentID:
        return self._agent.id

    async def deliberate[GoalT](
        self, *, question: CouncilQuestion, goal: GoalT, context: AgentContext
    ) -> Opinion:
        result = await self._agent.run(goal=goal, context=context)
        if not result.success or result.output is None:
            return Opinion(
                member_id=self._agent.id,
                choice=None,
                confidence=0.0,
                abstained=True,
                rationale=result.error or "agent produced no output",
            )
        raw = self._extract(result.output)
        if raw not in set(question.options):
            return Opinion(
                member_id=self._agent.id,
                choice=None,
                confidence=0.0,
                abstained=True,
                rationale=f"choice {raw!r} not in options",
                raw_choice=raw,
            )
        return Opinion(member_id=self._agent.id, choice=raw, confidence=1.0)


def create_agent_council(
    *,
    members: tuple[Agent[Any, Any] | CouncilMember, ...],
    config: CouncilConfig | None = None,
    aggregator: VoteAggregator | None = None,
    extract_choice: Callable[[Any], str] | None = None,
) -> AgentCouncil:
    """Factory (BYO-X) — wrap plain Agents as members; keep CouncilMembers as-is."""
    extract = extract_choice or str
    adapted: list[CouncilMember] = []
    for member in members:
        if isinstance(member, CouncilMember):
            adapted.append(member)
        else:
            adapted.append(_AgentMemberAdapter(agent=member, extract_choice=extract))
    cfg = config or CouncilConfig()
    return AgentCouncil(
        members=tuple(adapted),
        aggregator=aggregator or DefaultVoteAggregator(config=cfg),
        config=cfg,
    )
