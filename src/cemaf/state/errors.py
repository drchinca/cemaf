"""Errors raised by StateMachine.fire() — one class per failure outcome."""

from __future__ import annotations


class FsmError(Exception):
    """Base for all FSM errors."""


class TransitionNotAllowed(FsmError):
    """No `Transition` matches the (current_state, event) pair, or current_state is terminal."""


class GuardRejected(FsmError):
    """Transition's guard returned False — preconditions not met."""


class HitlRequired(FsmError):
    """Transition has requires_hitl=True and the caller's actor_kind is not 'human'."""


class HandlerFailed(FsmError):
    """Transition's handler raised — state was rolled back, no transition appended."""


class VersionConflict(FsmError):
    """Optimistic-locking collision — another fire() persisted a newer version first."""
