"""StateMachine[StateT, EventT] — typed, persisted, observable FSM core.

Invariants enforced:
- Typed states + events (StrEnum); plain strings rejected by type system
- Explicit transitions only (no fallthrough); duplicate (from_state, event)
  pairs rejected at construction time
- Optimistic locking via FsmStore.save(expected_version=...)
- HITL non-bypass — Transition.requires_hitl=True rejects actor_kind != "human"
- Append-only history (FsmState.history is replaced on copy, never mutated)
- Handler failure rolls back (new state never persisted)
- Terminal states absorbing
- Provenance — correlation_id required on every fire()
- No global state — instances created per FSM kind via DI
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from cemaf.state.errors import (
    GuardRejected,
    HandlerFailed,
    HitlRequired,
    TransitionNotAllowed,
)
from cemaf.state.persistence import FsmStore
from cemaf.state.transitions import (
    ACTOR_KIND_ANY,
    ACTOR_KIND_HUMAN,
    ActorKind,
    FsmState,
    StateTransition,
    Transition,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)


class StateMachine[StateT: StrEnum, EventT: StrEnum]:
    """Typed, persisted, observable FSM.

    Composition with DAGExecutor: a Transition.handler may dispatch a CEMAF DAG
    so that complex side-effects inherit observability via the shared
    correlation_id propagated through the FsmState passed to the handler.
    """

    def __init__(
        self,
        *,
        kind: str,
        states: type[StateT],
        events: type[EventT],
        transitions: list[Transition[StateT, EventT]],
        store: FsmStore,
        initial_state: StateT,
        terminal_states: frozenset[StateT] | None = None,
    ) -> None:
        if not kind:
            raise ValueError("kind must be a non-empty string")
        if initial_state not in states:
            raise ValueError(f"initial_state={initial_state!r} not in {states.__name__}")
        if terminal_states is not None:
            unknown = terminal_states - frozenset(states)
            if unknown:
                raise ValueError(f"terminal_states contains unknown states: {unknown!r}")

        self._kind = kind
        self._states = states
        self._events = events
        self._store = store
        self._initial_state = initial_state
        self._terminal_states: frozenset[StateT] = terminal_states or frozenset()
        self._index: dict[tuple[str, str], Transition[StateT, EventT]] = {}
        for transition in transitions:
            key = (str(transition.from_state), str(transition.event))
            if key in self._index:
                raise ValueError(
                    f"duplicate transition for ({transition.from_state}, {transition.event}) — "
                    "FSMs require deterministic dispatch"
                )
            self._index[key] = transition

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def states(self) -> type[StateT]:
        return self._states

    @property
    def events(self) -> type[EventT]:
        return self._events

    @property
    def terminal_states(self) -> frozenset[StateT]:
        return self._terminal_states

    @property
    def transitions(self) -> Iterable[Transition[StateT, EventT]]:
        return self._index.values()

    async def create(self, *, fsm_id: str, metadata: dict[str, object] | None = None) -> FsmState:
        existing = await self._store.load(fsm_id=fsm_id, kind=self._kind)
        if existing is not None:
            raise ValueError(f"fsm already exists: kind={self._kind} id={fsm_id}")
        state = FsmState(
            fsm_id=fsm_id,
            fsm_kind=self._kind,
            current_state=str(self._initial_state),
            history=[],
            metadata=dict(metadata) if metadata else {},
            version=0,
            updated_at=datetime.now(tz=UTC),
        )
        return await self._store.save(state=state, expected_version=0)

    async def current(self, *, fsm_id: str) -> FsmState:
        state = await self._store.load(fsm_id=fsm_id, kind=self._kind)
        if state is None:
            raise TransitionNotAllowed(f"fsm not found: kind={self._kind} id={fsm_id}")
        return state

    async def history(self, *, fsm_id: str, limit: int = 100) -> list[StateTransition]:
        state = await self.current(fsm_id=fsm_id)
        return list(state.history[-limit:])

    async def fire(
        self,
        *,
        fsm_id: str,
        event: EventT,
        actor: str,
        actor_kind: ActorKind,
        correlation_id: str,
        payload: dict[str, object] | None = None,
    ) -> FsmState:
        if not actor:
            raise ValueError("actor must be a non-empty string")
        if not correlation_id:
            raise ValueError("correlation_id must be a non-empty string")

        payload = payload or {}
        state = await self.current(fsm_id=fsm_id)
        current_state_str = state.current_state

        if any(str(t) == current_state_str for t in self._terminal_states):
            raise TransitionNotAllowed(f"current_state={current_state_str} is terminal for kind={self._kind}")

        key = (current_state_str, str(event))
        transition = self._index.get(key)
        if transition is None:
            raise TransitionNotAllowed(
                f"no transition from {current_state_str} on event {event} (kind={self._kind})"
            )

        if transition.requires_hitl and actor_kind != ACTOR_KIND_HUMAN:
            raise HitlRequired(
                f"transition {current_state_str} -[{event}]-> {transition.to_state} requires human actor"
            )

        if transition.actor_kind != ACTOR_KIND_ANY and transition.actor_kind != actor_kind:
            raise HitlRequired(
                f"transition {current_state_str} -[{event}]-> {transition.to_state} "
                f"requires actor_kind={transition.actor_kind} (got {actor_kind})"
            )

        if transition.guard is not None:
            try:
                allowed = await transition.guard(state, payload)
            except Exception as exc:
                log.warning(
                    "fsm.guard_raised",
                    extra={"kind": self._kind, "id": fsm_id, "event": str(event), "exc": type(exc).__name__},
                )
                raise GuardRejected(f"guard raised: {exc}") from exc
            if not allowed:
                raise GuardRejected(
                    f"guard rejected transition {current_state_str} -[{event}]-> {transition.to_state}"
                )

        now = datetime.now(tz=UTC)
        new_transition = StateTransition(
            from_state=current_state_str,
            to_state=str(transition.to_state),
            event=str(event),
            actor=actor,
            actor_kind=actor_kind,
            triggered_at=now,
            correlation_id=correlation_id,
            metadata=dict(payload) if payload else {},
        )
        new_state = state.model_copy(
            update={
                "current_state": str(transition.to_state),
                "history": [*state.history, new_transition],
                "version": state.version + 1,
                "updated_at": now,
            }
        )

        if transition.handler is not None:
            try:
                await transition.handler(new_state, payload)
            except Exception as exc:
                log.warning(
                    "fsm.handler_failed",
                    extra={
                        "kind": self._kind,
                        "id": fsm_id,
                        "event": str(event),
                        "exc": type(exc).__name__,
                    },
                )
                raise HandlerFailed(f"handler raised: {exc}") from exc

        return await self._store.save(state=new_state, expected_version=state.version)

    def graph_mermaid(self) -> str:
        """Render the FSM topology as a Mermaid stateDiagram-v2 — for spec docs + dashboards."""
        lines = ["stateDiagram-v2", f"    [*] --> {self._initial_state}"]
        for transition in self._index.values():
            label = str(transition.event)
            if transition.requires_hitl:
                label = f"{label} (HITL)"
            lines.append(f"    {transition.from_state} --> {transition.to_state} : {label}")
        for terminal in self._terminal_states:
            lines.append(f"    {terminal} --> [*]")
        return "\n".join(lines)
