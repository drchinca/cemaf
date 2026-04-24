"""
TrustLedger: Tracks reliability scores for tools and skills over time.

Promotes entities from UNTRUSTED → SANDBOXED → TRUSTED or DEPRECATED
based on observed execution outcomes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cemaf.core.enums import TrustLevel
from cemaf.core.types import TrustScore


@dataclass(frozen=True)
class TrustEntry:
    """Immutable record of a tool or skill's trust state."""

    entity_id: str              # ToolID or SkillID (stored as str for generality)
    entity_type: str            # "tool" | "skill"
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    trust_score: TrustScore = TrustScore(0.5)
    executions: int = 0
    successes: int = 0
    failures: int = 0
    avg_latency_ms: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""

    def record_execution(
        self,
        *,
        success: bool,
        latency_ms: float = 0.0,
    ) -> TrustEntry:
        """Return a new entry updated with a single execution outcome."""
        new_exec = self.executions + 1
        new_succ = self.successes + (1 if success else 0)
        new_fail = self.failures + (0 if success else 1)
        new_score = TrustScore(new_succ / new_exec)
        new_latency = (
            (self.avg_latency_ms * self.executions + latency_ms) / new_exec
        )
        new_level = self._compute_level(new_score, new_exec, new_fail)
        return TrustEntry(
            entity_id=self.entity_id,
            entity_type=self.entity_type,
            trust_level=new_level,
            trust_score=new_score,
            executions=new_exec,
            successes=new_succ,
            failures=new_fail,
            avg_latency_ms=new_latency,
            created_at=self.created_at,
            updated_at=datetime.utcnow(),
            notes=self.notes,
        )

    def _compute_level(
        self,
        score: float,
        executions: int,
        failures: int,
    ) -> TrustLevel:
        """Determine the appropriate TrustLevel from aggregate statistics."""
        if failures >= 5 and score < 0.3:
            return TrustLevel.DEPRECATED
        if executions >= 10 and score >= 0.85:
            return TrustLevel.TRUSTED
        if executions >= 3:
            return TrustLevel.SANDBOXED
        return TrustLevel.UNTRUSTED


class TrustLedger:
    """
    Persistent ledger tracking reliability of all dynamic tools/skills.

    Optionally backed by a JSON file so trust history survives restarts.
    All mutation methods return the updated ``TrustEntry``; the ledger itself
    is the single source of truth.
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        self._entries: dict[str, TrustEntry] = {}
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            self._load()

    def get(self, entity_id: str) -> TrustEntry | None:
        """Return the entry for ``entity_id``, or ``None`` if unknown."""
        return self._entries.get(entity_id)

    def get_or_create(
        self,
        entity_id: str,
        entity_type: str = "tool",
    ) -> TrustEntry:
        """Return an existing entry or create a fresh one at UNTRUSTED."""
        if entity_id not in self._entries:
            self._entries[entity_id] = TrustEntry(
                entity_id=entity_id,
                entity_type=entity_type,
            )
        return self._entries[entity_id]

    def record(
        self,
        entity_id: str,
        entity_type: str = "tool",
        *,
        success: bool,
        latency_ms: float = 0.0,
    ) -> TrustEntry:
        """Record a single execution outcome and return the updated entry."""
        entry = self.get_or_create(entity_id, entity_type)
        updated = entry.record_execution(success=success, latency_ms=latency_ms)
        self._entries[entity_id] = updated
        if self._persist_path:
            self._save()
        return updated

    def is_trusted(self, entity_id: str) -> bool:
        """True iff the entity has been promoted to TRUSTED."""
        entry = self._entries.get(entity_id)
        return entry is not None and entry.trust_level == TrustLevel.TRUSTED

    def is_deprecated(self, entity_id: str) -> bool:
        """True iff the entity has been marked DEPRECATED."""
        entry = self._entries.get(entity_id)
        return entry is not None and entry.trust_level == TrustLevel.DEPRECATED

    def should_sandbox(self, entity_id: str) -> bool:
        """True when execution should be wrapped in the LocalSandbox."""
        entry = self._entries.get(entity_id)
        if entry is None:
            return True
        return entry.trust_level in (TrustLevel.UNTRUSTED, TrustLevel.SANDBOXED)

    def list_all(self) -> tuple[TrustEntry, ...]:
        """Return all entries currently in the ledger."""
        return tuple(self._entries.values())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        assert self._persist_path is not None  # guarded by caller
        data = [
            {
                "entity_id": e.entity_id,
                "entity_type": e.entity_type,
                "trust_level": e.trust_level.value,
                "trust_score": e.trust_score,
                "executions": e.executions,
                "successes": e.successes,
                "failures": e.failures,
                "avg_latency_ms": e.avg_latency_ms,
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
                "notes": e.notes,
            }
            for e in self._entries.values()
        ]
        self._persist_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        assert self._persist_path is not None  # guarded by caller
        data = json.loads(self._persist_path.read_text())
        for item in data:
            self._entries[item["entity_id"]] = TrustEntry(
                entity_id=item["entity_id"],
                entity_type=item["entity_type"],
                trust_level=TrustLevel(item["trust_level"]),
                trust_score=TrustScore(float(item["trust_score"])),
                executions=int(item["executions"]),
                successes=int(item["successes"]),
                failures=int(item["failures"]),
                avg_latency_ms=float(item["avg_latency_ms"]),
                created_at=datetime.fromisoformat(item["created_at"]),
                updated_at=datetime.fromisoformat(item["updated_at"]),
                notes=str(item.get("notes", "")),
            )
