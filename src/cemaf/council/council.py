"""AgentCouncil — runs members concurrently, aggregates, records provenance (SPEC-10)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from cemaf.agents.base import AgentContext
from cemaf.agents.directory_protocols import AgentDirectory
from cemaf.agents.identity import AgentInstance
from cemaf.agents.protocols import Agent
from cemaf.core.enums import InstanceStatus
from cemaf.core.types import AgentID, AttemptID, RunID, TaskID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.protocols import CouncilMember, VoteAggregator
from cemaf.council.types import CouncilConfig, CouncilDecision, CouncilQuestion, Opinion
from cemaf.interceptors.types import COUNCIL_PRIOR_ROUND_KEY

logger = logging.getLogger(__name__)


class AgentCouncil:
    """Runs members concurrently (bounded + timed), aggregates, records provenance."""

    def __init__(
        self,
        *,
        members: tuple[CouncilMember, ...],
        aggregator: VoteAggregator,
        config: CouncilConfig | None = None,
        agent_directory: AgentDirectory | None = None,
    ) -> None:
        self._members = members
        self._aggregator = aggregator
        self._config = config or CouncilConfig()
        self._agent_directory = agent_directory

    async def decide[GoalT](
        self, *, question: CouncilQuestion, goal: GoalT, context: AgentContext
    ) -> CouncilDecision:
        """Run up to ``config.rounds`` rounds of deliberation.

        Round 1 is parallel independent voting (the ensemble baseline). Round 2+
        injects prior-round opinions under
        ``AgentContext.global_memory["council_prior_round"]`` so members that
        read it can revise their vote. Stops early when a round's tally matches
        the prior round's (settled vote — no point burning cost).
        """
        rounds = max(1, self._config.rounds)
        prior_opinions: tuple[Opinion, ...] = ()
        prior_tally: dict[str, float] | None = None
        decision: CouncilDecision | None = None

        for round_index in range(rounds):
            round_context = (
                context
                if round_index == 0
                else self._broadcast_context(context=context, prior_opinions=prior_opinions)
            )
            opinions = await self._run_round(
                question=question, goal=goal, context=round_context, round_index=round_index
            )
            decision = self._aggregator.aggregate(question=question, opinions=opinions)

            # Early-stop: if the tally is unchanged from the prior round, more
            # rounds won't change the outcome — return now and save cost.
            if prior_tally is not None and decision.tally == prior_tally:
                logger.info(
                    "council settled at round %d/%d (tally unchanged); stopping",
                    round_index + 1,
                    rounds,
                )
                break
            prior_opinions = opinions
            prior_tally = dict(decision.tally)

        if decision is None:  # pragma: no cover — CouncilConfig enforces rounds >= 1
            raise RuntimeError("AgentCouncil.decide produced no decision (rounds=0?)")

        # Every member participated across every round regardless of an
        # individual round's outcome (SPEC-18 §2.1) — no per-round terminal
        # state, since decide() can't know a round was "the last" until
        # after early-stop/exhaustion is decided right here.
        await self._complete_members(context=context)
        return decision

    async def _run_round[GoalT](
        self, *, question: CouncilQuestion, goal: GoalT, context: AgentContext, round_index: int
    ) -> tuple[Opinion, ...]:
        """One round of concurrent deliberation. Bounded + timed; raises become abstentions."""
        semaphore = asyncio.Semaphore(self._config.max_concurrency)
        timeout_s = self._config.member_timeout.total_seconds()

        async def run_member(member: CouncilMember) -> Opinion:
            async with semaphore:
                # Admission is idempotent across rounds (round-independent
                # spawn key) — same instance_id every round, new attempt_id
                # per round. Each member gets its own context copy carrying
                # its own instance_id; today's shared `context` object is
                # the base every member's copy derives from.
                instance = await self._admit_member(member=member, context=context)
                member_context = (
                    context.model_copy(update={"instance_id": instance.instance_id})
                    if instance is not None
                    else context
                )
                await self._transition_member(
                    instance,
                    context=context,
                    status=InstanceStatus.RUNNING,
                    attempt_id=AttemptID(f"{member.id}-round-{round_index}"),
                )
                try:
                    return await asyncio.wait_for(
                        member.deliberate(question=question, goal=goal, context=member_context),
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
        return tuple(opinions)

    @staticmethod
    def _broadcast_context(*, context: AgentContext, prior_opinions: tuple[Opinion, ...]) -> AgentContext:
        """Inject prior round's opinions under the namespaced council key.

        Members read ``COUNCIL_PRIOR_ROUND_KEY`` (dunder-namespaced so external
        code doesn't squat it) to see peers' votes and may revise; members that
        ignore it remain a parallel ensemble (round-1 behaviour).
        """
        broadcast = [
            {
                "member_id": str(o.member_id),
                "choice": o.choice,
                "confidence": o.confidence,
                "rationale": o.rationale,
                "abstained": o.abstained,
            }
            for o in prior_opinions
        ]
        return context.model_copy(
            update={
                "global_memory": {
                    **context.global_memory,
                    COUNCIL_PRIOR_ROUND_KEY: broadcast,
                }
            }
        )

    async def _admit_member(self, *, member: CouncilMember, context: AgentContext) -> AgentInstance | None:
        """Admit a per-member AgentInstance (SPEC-18 §2.1), or None if no directory is wired.

        Idempotent across rounds — the spawn key doesn't include round_index,
        so round 2+ replays the same instance rather than minting a new one.
        Failures are swallowed and logged; a broken directory must never
        break real deliberation.
        """
        if self._agent_directory is None:
            return None
        try:
            return await self._agent_directory.admit(
                spawn_key=f"{context.run_id}:{context.agent_id}:{member.id}",
                agent_id=AgentID(str(member.id)),
                task_id=TaskID(context.run_id),
                run_id=RunID(context.run_id),
                council_member_slot=str(member.id),
            )
        except Exception as e:
            logger.warning("AgentDirectory admit failed for council member %s: %s", member.id, e)
            return None

    async def _transition_member(
        self,
        instance: AgentInstance | None,
        *,
        context: AgentContext,
        status: InstanceStatus,
        attempt_id: AttemptID | None = None,
    ) -> None:
        """Best-effort lifecycle transition — no-op without a directory or instance."""
        if instance is None or self._agent_directory is None:
            return
        try:
            await self._agent_directory.transition(
                instance.instance_id, task_id=TaskID(context.run_id), status=status, attempt_id=attempt_id
            )
        except Exception as e:
            logger.warning("AgentDirectory transition failed for instance %s: %s", instance.instance_id, e)

    async def _complete_members(self, *, context: AgentContext) -> None:
        """Mark every member COMPLETED once deliberation is fully done (all rounds).

        No distinction between "abstained via timeout/exception" and
        "abstained on the merits" — every member that participated in the
        full decide() call gets COMPLETED, mirroring the council's own
        "no-decision is a legitimate outcome, not a failure" stance. The
        abstention reason stays visible in Opinion.rationale; this only
        affects the identity-lifecycle label.
        """
        if self._agent_directory is None:
            return
        for member in self._members:
            instance = await self._admit_member(member=member, context=context)
            await self._transition_member(instance, context=context, status=InstanceStatus.COMPLETED)


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
