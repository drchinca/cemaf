"""TCAS collision policy + run-scoped coordinator (SPEC-12).

``TcasCollisionPolicy`` turns a collision risk into a coordinated advisory using the two
thresholds and the deterministic right-of-way tiebreak. ``CollisionCoordinator`` holds the
run-scoped registry of intended write sets, guards it with a lock, and gates advice on a
cohort barrier so an agent never advises against peers that have not yet registered.
"""

import asyncio
import logging
from collections.abc import Callable

from cemaf.collision.protocols import Advisory, CollisionPolicy
from cemaf.collision.risk import (
    DEFAULT_GAMMA,
    DEFAULT_WEIGHTS,
    TAU_RESOLUTION_ADVISORY,
    TAU_TRAFFIC_ADVISORY,
    AdvisoryLevel,
    AgentWriteSet,
    ChannelWeights,
    CollisionChannels,
    collision_risk,
    has_right_of_way,
)
from cemaf.events.protocols import Event, EventBus, EventType

logger = logging.getLogger(__name__)

DEFAULT_COHORT_TIMEOUT_S: float = 5.0


class TcasCollisionPolicy:
    """Default CollisionPolicy — noisy-OR risk carved into CLEAR / TA / RA bands."""

    def __init__(
        self,
        *,
        dep_distance: Callable[[str, str], float] | None = None,
        weights: ChannelWeights = DEFAULT_WEIGHTS,
        gamma: float = DEFAULT_GAMMA,
        tau_traffic: float = TAU_TRAFFIC_ADVISORY,
        tau_resolution: float = TAU_RESOLUTION_ADVISORY,
    ) -> None:
        if not 0.0 <= tau_traffic <= tau_resolution <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= tau_traffic <= tau_resolution <= 1")
        self._dep_distance = dep_distance
        self._weights = weights
        self._gamma = gamma
        self._tau_traffic = tau_traffic
        self._tau_resolution = tau_resolution

    def advise(self, a: AgentWriteSet, b: AgentWriteSet) -> Advisory:
        """Compute the coordinated advisory between two intended write sets."""
        result = collision_risk(
            a=a,
            b=b,
            dep_distance=self._dep_distance,
            weights=self._weights,
            gamma=self._gamma,
        )
        risk, channels = result.risk, result.channels

        if risk < self._tau_traffic:
            return Advisory(
                level=AdvisoryLevel.CLEAR,
                risk=risk,
                channels=channels,
                transmit=False,
                steer=None,
                hold=None,
            )

        if risk < self._tau_resolution:
            return Advisory(
                level=AdvisoryLevel.TRAFFIC_ADVISORY,
                risk=risk,
                channels=channels,
                transmit=True,
                steer=None,
                hold=None,
            )

        a_holds = has_right_of_way(a=a, b=b)
        hold = a.agent_id if a_holds else b.agent_id
        steer = b.agent_id if a_holds else a.agent_id
        return Advisory(
            level=AdvisoryLevel.RESOLUTION_ADVISORY,
            risk=risk,
            channels=channels,
            transmit=True,
            steer=steer,
            hold=hold,
        )


_EMPTY_CHANNELS = CollisionChannels(overlap=0.0, dependency=0.0, tree=0.0)
_CLEAR = Advisory(level=AdvisoryLevel.CLEAR, risk=0.0, channels=_EMPTY_CHANNELS)


def _worst(left: Advisory, right: Advisory) -> Advisory:
    """Pick the higher-risk advisory (used to reduce many peers to one verdict)."""
    return left if left.risk >= right.risk else right


class CollisionCoordinator:
    """Run-scoped registry of intended write sets with a cohort-gated advisory query.

    Implements ``CollisionPolicy`` by delegating ``advise`` to the wrapped policy, and adds
    ``register`` / ``advise_against_cohort`` for live coordination across concurrent agents.
    """

    def __init__(
        self,
        *,
        policy: CollisionPolicy | None = None,
        cohort_size: int | None = None,
        cohort_timeout_s: float = DEFAULT_COHORT_TIMEOUT_S,
    ) -> None:
        if cohort_size is not None and cohort_size < 1:
            raise ValueError("cohort_size must be >= 1 when set")
        if cohort_timeout_s <= 0:
            raise ValueError("cohort_timeout_s must be positive")
        self._policy: CollisionPolicy = policy or TcasCollisionPolicy()
        self._cohort_size = cohort_size
        self._cohort_timeout_s = cohort_timeout_s
        self._registry: dict[str, AgentWriteSet] = {}
        self._lock = asyncio.Lock()
        self._cohort_ready = asyncio.Event()

    def advise(self, a: AgentWriteSet, b: AgentWriteSet) -> Advisory:
        """Delegate the pairwise advisory to the wrapped policy."""
        return self._policy.advise(a=a, b=b)

    async def register(self, write_set: AgentWriteSet) -> None:
        """Register (or replace) an agent's intended write set for this run.

        ``cohort_size`` MUST equal the true number of distinct agents in the cohort; a
        registry that grows beyond it means the count was misconfigured (a peer would be
        invisible to callers that already passed the barrier) — logged loudly.
        """
        async with self._lock:
            is_new = write_set.agent_id not in self._registry
            self._registry[write_set.agent_id] = write_set
            count = len(self._registry)
            if self._cohort_size is not None:
                if count >= self._cohort_size:
                    self._cohort_ready.set()
                if is_new and count > self._cohort_size:
                    logger.warning(
                        "collision cohort overflow: %d distinct agents registered but "
                        "cohort_size=%d — peers may have advised before %r registered",
                        count,
                        self._cohort_size,
                        write_set.agent_id,
                    )

    async def advise_against_cohort(self, agent_id: str) -> Advisory:
        """Return the worst advisory between ``agent_id`` and every other registered peer.

        When a cohort size is set, waits (bounded by ``cohort_timeout_s``) until that many
        agents have registered — preventing a false CLEAR from advising before peers have
        declared their intended writes. On timeout it degrades to advising against whoever
        has registered so far, logging a warning, rather than deadlocking the run.
        """
        if self._cohort_size is not None:
            try:
                await asyncio.wait_for(self._cohort_ready.wait(), timeout=self._cohort_timeout_s)
            except TimeoutError:
                logger.warning(
                    "collision cohort barrier timed out after %.1fs for %r — advising "
                    "against %d registered peer(s); a cohort member never registered",
                    self._cohort_timeout_s,
                    agent_id,
                    len(self._registry),
                )
        async with self._lock:
            mine = self._registry.get(agent_id)
            peers = [ws for aid, ws in self._registry.items() if aid != agent_id]
        if mine is None:
            return _CLEAR
        worst = _CLEAR
        for peer in peers:
            worst = _worst(worst, self._policy.advise(a=mine, b=peer))
        return worst


async def emit_advisory(
    *,
    event_bus: EventBus,
    advisory: Advisory,
    agent_id: str,
    source: str = "collision_coordinator",
    correlation_id: str | None = None,
) -> bool:
    """Publish a CONTEXT_CONFLICT event for an advisory at TRAFFIC_ADVISORY and above.

    Returns True if an event was published, False for a CLEAR advisory (no conflict).
    This is the reusable bridge a live run uses to surface coordination on the EventBus.
    """
    if not advisory.transmit:
        return False
    await event_bus.publish(
        Event.create(
            type=EventType.CONTEXT_CONFLICT,
            payload={
                "agent_id": agent_id,
                "level": advisory.level.value,
                "risk": advisory.risk,
                "steer": advisory.steer,
                "hold": advisory.hold,
                "channels": {
                    "overlap": advisory.channels.overlap,
                    "dependency": advisory.channels.dependency,
                    "tree": advisory.channels.tree,
                },
            },
            source=source,
            correlation_id=correlation_id,
        )
    )
    return True
