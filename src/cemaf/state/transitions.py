"""Transition + FsmState + StateTransition — the type vocabulary of the FSM primitive."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ACTOR_KIND_HUMAN: Literal["human"] = "human"
ACTOR_KIND_AGENT: Literal["agent"] = "agent"
ACTOR_KIND_ANY: Literal["any"] = "any"

type ActorKind = Literal["human", "agent"]
type AllowedActorKind = Literal["human", "agent", "any"]
type Guard = Callable[["FsmState", dict[str, object]], Awaitable[bool]]
type Handler = Callable[["FsmState", dict[str, object]], Awaitable[None]]


class StateTransition(BaseModel):
    """Append-only audit row — one per successful fire()."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_state: str
    to_state: str
    event: str
    actor: str
    actor_kind: ActorKind
    triggered_at: datetime
    correlation_id: str
    metadata: dict[str, object] = Field(default_factory=dict)


class FsmState(BaseModel):
    """Persisted FSM record — drivers serialize/deserialize this."""

    model_config = ConfigDict(extra="forbid")

    fsm_id: str
    fsm_kind: str
    current_state: str
    history: list[StateTransition] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    version: int = 0
    updated_at: datetime


class Transition[StateT: StrEnum, EventT: StrEnum](BaseModel):
    """A single allowed transition. Authored at FSM definition time."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    from_state: StateT
    event: EventT
    to_state: StateT
    guard: Guard | None = None
    handler: Handler | None = None
    requires_hitl: bool = False
    actor_kind: AllowedActorKind = ACTOR_KIND_ANY
