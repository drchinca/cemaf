"""Collision advisory types and the CollisionPolicy protocol (SPEC-12)."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cemaf.collision.risk import AdvisoryLevel, AgentWriteSet, CollisionChannels


@dataclass(frozen=True, slots=True)
class Advisory:
    """A coordinated collision advisory between two agents.

    At TRAFFIC_ADVISORY and above ``transmit`` is True (agents should exchange intent).
    At RESOLUTION_ADVISORY exactly one agent is ``steer`` (must defer) and the other is
    ``hold`` (has right-of-way); both are None below resolution.
    """

    level: AdvisoryLevel
    risk: float
    channels: CollisionChannels
    transmit: bool = False
    steer: str | None = None
    hold: str | None = None


@runtime_checkable
class CollisionPolicy(Protocol):
    """Decides the advisory between two intended write sets."""

    def advise(self, a: AgentWriteSet, b: AgentWriteSet) -> Advisory: ...
