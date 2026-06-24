"""Factory helpers for self-improvement runtime components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cemaf.improvement.loop import SelfImprovementLoop
from cemaf.memory.strategy import StrategyMemory
from cemaf.trust.ledger import TrustLedger


@dataclass(frozen=True)
class ImprovementRuntime:
    """Bundled self-improvement runtime dependencies."""

    strategy_memory: StrategyMemory
    trust_ledger: TrustLedger
    loop: SelfImprovementLoop


def create_strategy_memory(*, persist_path: str | Path | None = None) -> StrategyMemory:
    """Create a strategy memory store, optionally persisted to disk."""
    path = Path(persist_path) if persist_path is not None else None
    return StrategyMemory(persist_path=path)


def create_trust_ledger(*, persist_path: str | Path | None = None) -> TrustLedger:
    """Create a trust ledger, optionally persisted to disk."""
    path = Path(persist_path) if persist_path is not None else None
    return TrustLedger(persist_path=path)


def create_improvement_runtime(
    *,
    persist_dir: str | Path | None = None,
    strategy_filename: str = "strategy_memory.json",
    trust_filename: str = "trust_ledger.json",
    quality_threshold: float = 0.6,
) -> ImprovementRuntime:
    """Create a self-improvement runtime bundle with optional file persistence."""
    strategy_path: Path | None = None
    trust_path: Path | None = None

    if persist_dir is not None:
        root = Path(persist_dir)
        root.mkdir(parents=True, exist_ok=True)
        strategy_path = root / strategy_filename
        trust_path = root / trust_filename
        _ensure_json_array_file(strategy_path)
        _ensure_json_array_file(trust_path)

    strategy_memory = create_strategy_memory(persist_path=strategy_path)
    trust_ledger = create_trust_ledger(persist_path=trust_path)
    loop = SelfImprovementLoop(
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        quality_threshold=quality_threshold,
    )
    return ImprovementRuntime(
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        loop=loop,
    )


def _ensure_json_array_file(path: Path) -> None:
    if not path.exists():
        path.write_text("[]", encoding="utf-8")
