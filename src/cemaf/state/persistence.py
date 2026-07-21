"""FsmStore protocol + InMemoryFsmStore default impl.

For persistence across runs use `cemaf.state.sqlite_store.SqliteFsmStore`
(backend="sqlite" via create_fsm_store). A PostgresFsmStore can be added when
multi-host persistence is needed — InMemory is sufficient for tests and
single-process deployments.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from cemaf.state.errors import VersionConflict
from cemaf.state.transitions import FsmState


@runtime_checkable
class FsmStore(Protocol):
    """Storage abstraction for FSM state."""

    async def load(self, *, fsm_id: str, kind: str) -> FsmState | None: ...

    async def save(self, *, state: FsmState, expected_version: int) -> FsmState: ...

    async def list(self, *, kind: str, current_state: str | None = None) -> list[FsmState]: ...


class InMemoryFsmStore:
    """Reference implementation — async-safe within a single process."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], FsmState] = {}
        self._lock = asyncio.Lock()

    async def load(self, *, fsm_id: str, kind: str) -> FsmState | None:
        async with self._lock:
            return self._store.get((kind, fsm_id))

    async def save(self, *, state: FsmState, expected_version: int) -> FsmState:
        async with self._lock:
            key = (state.fsm_kind, state.fsm_id)
            current = self._store.get(key)
            current_version = current.version if current is not None else 0
            if current_version != expected_version:
                raise VersionConflict(
                    f"expected_version={expected_version} but stored={current_version} for {key!r}"
                )
            self._store[key] = state
            return state

    async def list(self, *, kind: str, current_state: str | None = None) -> list[FsmState]:
        async with self._lock:
            results = [s for (k, _), s in self._store.items() if k == kind]
        if current_state is not None:
            results = [s for s in results if s.current_state == current_state]
        return results
