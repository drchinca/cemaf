"""Durable run leases and fencing for checkpoint ownership."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from cemaf.core.types import RunID
from cemaf.core.utils import utc_now
from cemaf.orchestration.checkpointer import Checkpointer, DAGCheckpoint
from cemaf.persistence.atomic_file import atomic_write_text, process_file_lock


class StaleRunLeaseError(RuntimeError):
    """A worker attempted to mutate state after losing ownership."""


@dataclass(frozen=True)
class RunLease:
    """Exclusive, TTL-bounded ownership token for one run."""

    run_id: RunID
    holder_id: str
    fencing_token: int
    expires_at: datetime


@runtime_checkable
class RunLeaseStore(Protocol):
    """Protocol for durable run ownership backends."""

    async def acquire(
        self,
        run_id: RunID,
        holder_id: str,
        *,
        ttl: timedelta,
    ) -> RunLease | None: ...

    async def validate(self, lease: RunLease) -> bool: ...

    async def release(self, lease: RunLease) -> None: ...


class FileRunLeaseStore:
    """Cross-process file lease store with monotonic fencing tokens."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    async def acquire(
        self,
        run_id: RunID,
        holder_id: str,
        *,
        ttl: timedelta,
    ) -> RunLease | None:
        if ttl.total_seconds() <= 0:
            raise ValueError("lease ttl must be positive")
        now = utc_now()
        with process_file_lock(self._lock_path(run_id)):
            state = self._load_state(run_id)
            current_holder = state.get("holder_id")
            expires_at = _parse_datetime(state.get("expires_at"))
            if current_holder and expires_at is not None and expires_at > now:
                return None
            token = _parse_token(state.get("fencing_token")) + 1
            lease = RunLease(
                run_id=run_id,
                holder_id=holder_id,
                fencing_token=token,
                expires_at=now + ttl,
            )
            self._write_state(lease)
            return lease

    async def validate(self, lease: RunLease) -> bool:
        with process_file_lock(self._lock_path(lease.run_id)):
            state = self._load_state(lease.run_id)
            expires_at = _parse_datetime(state.get("expires_at"))
            return bool(
                state.get("holder_id") == lease.holder_id
                and _parse_token(state.get("fencing_token")) == lease.fencing_token
                and expires_at is not None
                and expires_at > utc_now()
            )

    async def release(self, lease: RunLease) -> None:
        with process_file_lock(self._lock_path(lease.run_id)):
            state = self._load_state(lease.run_id)
            if (
                state.get("holder_id") != lease.holder_id
                or _parse_token(state.get("fencing_token")) != lease.fencing_token
            ):
                raise StaleRunLeaseError(f"run {lease.run_id} is no longer owned by {lease.holder_id}")
            self._write_raw_state(
                run_id=lease.run_id,
                holder_id=None,
                fencing_token=lease.fencing_token,
                expires_at=None,
            )

    def _safe_name(self, run_id: RunID) -> str:
        return str(run_id).replace(":", "-").replace("/", "-")

    def _state_path(self, run_id: RunID) -> Path:
        return self._root / f"{self._safe_name(run_id)}.lease.json"

    def _lock_path(self, run_id: RunID) -> Path:
        return self._root / f"{self._safe_name(run_id)}.lease.lock"

    def _load_state(self, run_id: RunID) -> dict[str, object]:
        path = self._state_path(run_id)
        if not path.is_file():
            return {}
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"invalid lease state in {path}")
        return {str(key): value for key, value in payload.items()}

    def _write_state(self, lease: RunLease) -> None:
        self._write_raw_state(
            run_id=lease.run_id,
            holder_id=lease.holder_id,
            fencing_token=lease.fencing_token,
            expires_at=lease.expires_at,
        )

    def _write_raw_state(
        self,
        *,
        run_id: RunID,
        holder_id: str | None,
        fencing_token: int,
        expires_at: datetime | None,
    ) -> None:
        atomic_write_text(
            self._state_path(run_id),
            json.dumps(
                {
                    "run_id": str(run_id),
                    "holder_id": holder_id,
                    "fencing_token": fencing_token,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                indent=2,
            ),
        )


class FencedCheckpointer:
    """Checkpointer adapter that rejects stale lease holders."""

    def __init__(
        self,
        *,
        inner: Checkpointer,
        lease_store: RunLeaseStore,
        lease: RunLease,
    ) -> None:
        self._inner = inner
        self._lease_store = lease_store
        self._lease = lease

    async def save(self, checkpoint: DAGCheckpoint) -> None:
        await self._assert_current(checkpoint.run_id)
        await self._inner.save(replace(checkpoint, fencing_token=self._lease.fencing_token))

    async def load(self, run_id: RunID) -> DAGCheckpoint | None:
        return await self._inner.load(run_id)

    async def delete(self, run_id: RunID) -> bool:
        await self._assert_current(run_id)
        return await self._inner.delete(run_id)

    async def _assert_current(self, run_id: RunID) -> None:
        if run_id != self._lease.run_id or not await self._lease_store.validate(self._lease):
            raise StaleRunLeaseError(f"stale lease holder {self._lease.holder_id} for run {run_id}")


def _parse_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def _parse_token(value: object) -> int:
    if isinstance(value, (int, str)):
        return int(value)
    return 0
