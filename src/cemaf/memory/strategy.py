"""
StrategyMemory: Cross-run learned strategies.

Stores what worked and what didn't across executions.
Keyed by (task_pattern, approach) — a SHA-256-derived 16-char hex digest.
Values: StrategyRecord with success rate, approach text, and timing.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON, StrategyID, TrustScore
from cemaf.memory.base import InMemoryStore, MemoryItem


@dataclass(frozen=True)
class StrategyRecord:
    """Immutable record of an observed approach to a class of task."""

    strategy_id: StrategyID
    task_pattern: str  # Regex or free-text description of when to apply
    approach: str  # What to do
    success_count: int = 0
    failure_count: int = 0
    avg_quality_score: float = 0.0
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: JSON = field(default_factory=dict)

    @property
    def trust_score(self) -> TrustScore:
        """Ratio of successes to total executions (0.5 when no history)."""
        total = self.success_count + self.failure_count
        if total == 0:
            return TrustScore(0.5)
        return TrustScore(self.success_count / total)

    @property
    def is_viable(self) -> bool:
        """True when this strategy is worth trying again."""
        return self.trust_score >= 0.4 and self.failure_count < 10

    def with_outcome(self, success: bool, quality: float = 0.0) -> StrategyRecord:
        """Return a new record updated with the latest execution outcome."""
        new_success = self.success_count + (1 if success else 0)
        new_failure = self.failure_count + (0 if success else 1)
        total = new_success + new_failure
        new_quality = (self.avg_quality_score * (total - 1) + quality) / total
        return StrategyRecord(
            strategy_id=self.strategy_id,
            task_pattern=self.task_pattern,
            approach=self.approach,
            success_count=new_success,
            failure_count=new_failure,
            avg_quality_score=new_quality,
            last_used=datetime.now(UTC),
            metadata=self.metadata,
        )


class StrategyMemory:
    """
    Persistent memory for learned strategies.

    Backed by ``InMemoryStore`` (``MemoryScope.STRATEGY``) with optional
    JSON-file persistence so strategies survive process restarts.
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        self._store = InMemoryStore()
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            self._load(persist_path)

    async def record_outcome(
        self,
        task_pattern: str,
        approach: str,
        *,
        success: bool,
        quality: float = 0.0,
        metadata: JSON | None = None,
    ) -> StrategyRecord:
        """Update or create a strategy record with an execution outcome.

        Returns the updated (immutable) StrategyRecord.
        """
        key = self._key(task_pattern, approach)
        existing = await self._store.get(MemoryScope.STRATEGY, key)

        if existing:
            record: StrategyRecord = self._deserialize(existing.value)
        else:
            record = StrategyRecord(
                strategy_id=StrategyID(str(uuid.uuid4())),
                task_pattern=task_pattern,
                approach=approach,
                metadata=metadata or {},
            )

        updated = record.with_outcome(success, quality)
        item = MemoryItem(
            scope=MemoryScope.STRATEGY,
            key=key,
            value=self._serialize(updated),
        )
        await self._store.set(item)

        if self._persist_path:
            await self._save()

        return updated

    async def get_best_strategy(self, task_pattern: str) -> StrategyRecord | None:
        """Return the highest-scoring viable strategy for a given task pattern.

        Returns ``None`` when no viable strategies exist.
        """
        all_items = await self._store.list_by_scope(MemoryScope.STRATEGY)
        candidates = [
            self._deserialize(item.value)
            for item in all_items
            if item.value.get("task_pattern") == task_pattern
        ]
        viable = [s for s in candidates if s.is_viable]
        if not viable:
            return None
        return max(viable, key=lambda s: s.trust_score)

    async def list_strategies(self) -> tuple[StrategyRecord, ...]:
        """Return all strategy records currently stored."""
        all_items = await self._store.list_by_scope(MemoryScope.STRATEGY)
        return tuple(self._deserialize(item.value) for item in all_items)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key(self, task_pattern: str, approach: str) -> str:
        import hashlib

        return hashlib.sha256(f"{task_pattern}::{approach}".encode()).hexdigest()[:16]

    def _serialize(self, record: StrategyRecord) -> JSON:
        return {
            "strategy_id": record.strategy_id,
            "task_pattern": record.task_pattern,
            "approach": record.approach,
            "success_count": record.success_count,
            "failure_count": record.failure_count,
            "avg_quality_score": record.avg_quality_score,
            "last_used": record.last_used.isoformat(),
            "metadata": record.metadata,
        }

    def _deserialize(self, data: JSON) -> StrategyRecord:
        return StrategyRecord(
            strategy_id=StrategyID(str(data["strategy_id"])),
            task_pattern=str(data["task_pattern"]),
            approach=str(data["approach"]),
            success_count=int(data["success_count"]),
            failure_count=int(data["failure_count"]),
            avg_quality_score=float(data["avg_quality_score"]),
            last_used=datetime.fromisoformat(str(data["last_used"])),
            metadata=dict(data.get("metadata") or {}),
        )

    def _load(self, path: Path) -> None:
        """Synchronously pre-load persisted strategies at construction time."""
        data: list[Any] = json.loads(path.read_text())
        for entry in data:
            record = self._deserialize(entry)
            key = self._key(record.task_pattern, record.approach)
            item = MemoryItem(
                scope=MemoryScope.STRATEGY,
                key=key,
                value=entry,
            )
            self._store._data[item.full_key] = item

    async def _save(self) -> None:
        """Persist all current strategies to the configured JSON file."""
        all_items = await self._store.list_by_scope(MemoryScope.STRATEGY)
        data = [item.value for item in all_items]
        assert self._persist_path is not None  # guarded by caller
        self._persist_path.write_text(json.dumps(data, indent=2))
