"""Protocols for self-improvement runtime collaborators."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from cemaf.core.types import JSON
from cemaf.memory.strategy import StrategyRecord
from cemaf.trust.ledger import TrustEntry

if TYPE_CHECKING:
    from cemaf.core.result import Result
    from cemaf.improvement.loop import ExecutionSummary, ImprovementOutcome


@runtime_checkable
class StrategyMemoryBackend(Protocol):
    """Storage contract required by the self-improvement loop."""

    async def record_outcome(
        self,
        task_pattern: str,
        approach: str,
        *,
        success: bool,
        quality: float = 0.0,
        metadata: JSON | None = None,
    ) -> StrategyRecord: ...

    async def get_best_strategy(self, task_pattern: str) -> StrategyRecord | None: ...

    async def list_strategies(self) -> tuple[StrategyRecord, ...]: ...


@runtime_checkable
class TrustLedgerBackend(Protocol):
    """Trust ledger contract required by the self-improvement loop."""

    def get(self, entity_id: str) -> TrustEntry | None: ...

    def record(
        self,
        entity_id: str,
        entity_type: str = "tool",
        *,
        success: bool,
        latency_ms: float = 0.0,
    ) -> TrustEntry: ...


@runtime_checkable
class SelfImprovementProcessor(Protocol):
    """Processes an execution summary into persistent improvement signals."""

    async def process(self, summary: ExecutionSummary) -> Result[ImprovementOutcome]: ...


__all__ = [
    "SelfImprovementProcessor",
    "StrategyMemoryBackend",
    "TrustLedgerBackend",
]
