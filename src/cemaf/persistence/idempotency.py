"""Idempotent effect-sink protocol and crash-safe local implementation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.persistence.atomic_file import atomic_write_text, process_file_lock


class IdempotencyConflictError(RuntimeError):
    """An idempotency key was reused with a different payload."""


@dataclass(frozen=True)
class EffectReceipt:
    key: str
    created: bool
    payload: JSON


@runtime_checkable
class IdempotentEffectSink(Protocol):
    async def publish(self, *, key: str, payload: JSON) -> EffectReceipt: ...


class FileIdempotentEffectSink:
    """Store each effect once using atomic exclusive file creation.

    This is a concrete local destination, not a wrapper around an arbitrary
    non-transactional API. Production adapters must pass the same idempotency
    key through to a destination that enforces it or use a transactional outbox.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    async def publish(self, *, key: str, payload: JSON) -> EffectReceipt:
        path = self._path_for(key)
        envelope = json.dumps({"key": key, "payload": payload}, sort_keys=True)
        with process_file_lock(path.with_suffix(path.suffix + ".lock")):
            if path.is_file():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing.get("key") != key or existing.get("payload") != payload:
                    raise IdempotencyConflictError(f"payload conflict for idempotency key {key!r}")
                return EffectReceipt(key=key, created=False, payload=payload)
            atomic_write_text(path, envelope)
            return EffectReceipt(key=key, created=True, payload=payload)

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self._root / f"{digest}.effect.json"
