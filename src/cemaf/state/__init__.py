"""CEMAF State — typed, persisted, observable state machines.

First-class CEMAF primitive alongside agents/orchestration/memory/evals.

A `StateMachine[StateT, EventT]` is parameterized by two `StrEnum` types and a
list of `Transition`s. It composes with `DAGExecutor` (a transition handler may
dispatch a DAG) and with any `FsmStore` implementation for persistence.

Public surface is protocol-first and pluggable — bring your own `FsmStore`,
your own state and event enums, and your own guard / handler functions.
"""

from cemaf.state.errors import (
    FsmError,
    GuardRejected,
    HandlerFailed,
    HitlRequired,
    TransitionNotAllowed,
    VersionConflict,
)
from cemaf.state.fsm import StateMachine
from cemaf.state.persistence import FsmStore, InMemoryFsmStore
from cemaf.state.transitions import FsmState, StateTransition, Transition

__all__ = [
    "FsmError",
    "FsmState",
    "FsmStore",
    "GuardRejected",
    "HandlerFailed",
    "HitlRequired",
    "InMemoryFsmStore",
    "StateMachine",
    "StateTransition",
    "Transition",
    "TransitionNotAllowed",
    "VersionConflict",
]
