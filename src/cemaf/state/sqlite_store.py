"""SQLite-backed persistent FsmStore implementation.

Durable FSM persistence for single-host deployments, mirroring the connection
discipline of `cemaf.memory.sqlite_store`:
- One long-lived aiosqlite connection per store instance (opened lazily)
- WAL journal mode for concurrent readers + one writer without blocking
- busy_timeout so SQLITE_BUSY turns into a bounded wait instead of an error
- asyncio.Lock serializes in-process writes to the connection
- a process-global writer lane (per db path) serializes writes across separate
  store instances / event loops / threads pointed at the same database
- explicit close() for graceful shutdown

Optimistic locking matches InMemoryFsmStore exactly: a missing row counts as
version 0, and a `save(expected_version=...)` mismatch raises VersionConflict.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import aiosqlite

from cemaf.state.errors import VersionConflict
from cemaf.state.transitions import FsmState

# Process-global writer locks keyed by absolute db path — same rationale as
# cemaf.memory.sqlite_store: a per-instance asyncio.Lock only serializes within
# one event loop; instances on different loops/threads need a shared OS lock.
_WRITER_LANES: dict[str, threading.Lock] = {}
_WRITER_LANES_GUARD = threading.Lock()


def _writer_lane(db_path: str) -> threading.Lock:
    """Return the process-global write lock for a db path (in-memory dbs excepted)."""
    key = str(Path(db_path).resolve()) if db_path != ":memory:" else db_path
    with _WRITER_LANES_GUARD:
        lane = _WRITER_LANES.get(key)
        if lane is None:
            lane = threading.Lock()
            _WRITER_LANES[key] = lane
        return lane


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS fsm_states (
    fsm_kind TEXT NOT NULL,
    fsm_id TEXT NOT NULL,
    current_state TEXT NOT NULL,
    version INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (fsm_kind, fsm_id)
)
"""

_CREATE_INDEX_STATE = (
    "CREATE INDEX IF NOT EXISTS idx_fsm_states_kind_state ON fsm_states(fsm_kind, current_state)"
)


class SqliteFsmStore:
    """Persistent FsmStore backed by SQLite via aiosqlite."""

    def __init__(
        self,
        *,
        db_path: str = "cemaf_fsm.db",
        busy_timeout_ms: int = 5000,
        journal_mode: str = "WAL",
    ) -> None:
        self._db_path = db_path
        self._busy_timeout_ms = busy_timeout_ms
        self._journal_mode = journal_mode
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._writer_lane = _writer_lane(db_path)

    async def __aenter__(self) -> SqliteFsmStore:
        """Allow `async with` usage for deterministic connection cleanup."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        await self.close()

    async def _connection(self) -> aiosqlite.Connection:
        """Return the lazy-initialized, pragma-tuned connection."""
        if self._conn is not None:
            return self._conn
        async with self._lock:
            if self._conn is not None:  # double-check after acquire
                return self._conn
            conn = await aiosqlite.connect(self._db_path)
            await self._acquire_writer_lane()
            try:
                await conn.execute(f"PRAGMA journal_mode={self._journal_mode}")
                await conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute(_CREATE_TABLE)
                await conn.execute(_CREATE_INDEX_STATE)
                await conn.commit()
            finally:
                self._release_writer_lane()
            self._conn = conn
        return self._conn

    async def _acquire_writer_lane(self) -> None:
        """Acquire the process-global write lock without blocking the event loop."""
        backoff = 0.0005
        while not self._writer_lane.acquire(blocking=False):
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 0.05)

    def _release_writer_lane(self) -> None:
        self._writer_lane.release()

    async def close(self) -> None:
        """Close the underlying connection. Idempotent."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def load(self, *, fsm_id: str, kind: str) -> FsmState | None:
        """Load one FSM record, or None when it has never been saved."""
        conn = await self._connection()
        async with conn.execute(
            "SELECT state_json FROM fsm_states WHERE fsm_kind = ? AND fsm_id = ?",
            (kind, fsm_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return FsmState.model_validate_json(row[0])

    async def save(self, *, state: FsmState, expected_version: int) -> FsmState:
        """Persist under optimistic lock — a missing row counts as version 0."""
        conn = await self._connection()
        await self._acquire_writer_lane()
        try:
            async with self._lock:
                async with conn.execute(
                    "SELECT version FROM fsm_states WHERE fsm_kind = ? AND fsm_id = ?",
                    (state.fsm_kind, state.fsm_id),
                ) as cursor:
                    row = await cursor.fetchone()
                current_version = int(row[0]) if row is not None else 0
                if current_version != expected_version:
                    raise VersionConflict(
                        f"expected_version={expected_version} but stored={current_version} "
                        f"for {(state.fsm_kind, state.fsm_id)!r}"
                    )
                await conn.execute(
                    "INSERT OR REPLACE INTO fsm_states "
                    "(fsm_kind, fsm_id, current_state, version, state_json, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        state.fsm_kind,
                        state.fsm_id,
                        state.current_state,
                        state.version,
                        state.model_dump_json(),
                        state.updated_at.isoformat(),
                    ),
                )
                await conn.commit()
        finally:
            self._release_writer_lane()
        return state

    async def list(self, *, kind: str, current_state: str | None = None) -> list[FsmState]:
        """List FSM records of a kind, optionally narrowed to one current state."""
        conn = await self._connection()
        if current_state is None:
            query = "SELECT state_json FROM fsm_states WHERE fsm_kind = ?"
            params: tuple[str, ...] = (kind,)
        else:
            query = "SELECT state_json FROM fsm_states WHERE fsm_kind = ? AND current_state = ?"
            params = (kind, current_state)
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [FsmState.model_validate_json(row[0]) for row in rows]
