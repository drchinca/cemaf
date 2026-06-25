"""Factory helpers for self-improvement runtime components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cemaf.core.provider_registry import ProviderRegistry
from cemaf.improvement.loop import SelfImprovementLoop
from cemaf.improvement.protocols import (
    SelfImprovementProcessor,
    StrategyMemoryBackend,
    TrustLedgerBackend,
)
from cemaf.memory.strategy import StrategyMemory
from cemaf.trust.ledger import TrustLedger

strategy_memory_registry: ProviderRegistry[StrategyMemoryBackend] = ProviderRegistry(name="strategy_memory")
trust_ledger_registry: ProviderRegistry[TrustLedgerBackend] = ProviderRegistry(name="trust_ledger")
improvement_loop_registry: ProviderRegistry[SelfImprovementProcessor] = ProviderRegistry(
    name="improvement_loop"
)


@dataclass(frozen=True)
class ImprovementRuntime:
    """Bundled self-improvement runtime dependencies."""

    strategy_memory: StrategyMemoryBackend
    trust_ledger: TrustLedgerBackend
    loop: SelfImprovementProcessor


def _create_strategy_memory(**kwargs: Any) -> StrategyMemoryBackend:
    persist_path = kwargs.get("persist_path")
    path = Path(persist_path) if persist_path is not None else None
    return StrategyMemory(persist_path=path)


def _create_trust_ledger(**kwargs: Any) -> TrustLedgerBackend:
    persist_path = kwargs.get("persist_path")
    path = Path(persist_path) if persist_path is not None else None
    return TrustLedger(persist_path=path)


def _create_self_improvement_loop(**kwargs: Any) -> SelfImprovementProcessor:
    strategy_memory = kwargs.get("strategy_memory")
    trust_ledger = kwargs.get("trust_ledger")
    if strategy_memory is None:
        raise ValueError("default improvement loop backend requires strategy_memory.")
    if trust_ledger is None:
        raise ValueError("default improvement loop backend requires trust_ledger.")
    return SelfImprovementLoop(
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        quality_threshold=float(kwargs.get("quality_threshold", 0.6)),
    )


strategy_memory_registry.register(backend="memory", factory=_create_strategy_memory)
strategy_memory_registry.register(backend="json_file", factory=_create_strategy_memory)
trust_ledger_registry.register(backend="memory", factory=_create_trust_ledger)
trust_ledger_registry.register(backend="json_file", factory=_create_trust_ledger)
improvement_loop_registry.register(backend="default", factory=_create_self_improvement_loop)


def create_self_improvement_loop(
    *,
    strategy_memory: StrategyMemoryBackend,
    trust_ledger: TrustLedgerBackend,
    backend: str = "default",
    quality_threshold: float = 0.6,
    **backend_options: Any,
) -> SelfImprovementProcessor:
    """Create the default self-improvement loop from runtime dependencies."""
    return improvement_loop_registry.create(
        backend=backend,
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        quality_threshold=quality_threshold,
        **backend_options,
    )


def create_strategy_memory(
    *,
    backend: str = "memory",
    persist_path: str | Path | None = None,
    **backend_options: Any,
) -> StrategyMemoryBackend:
    """Create a strategy memory store, optionally persisted to disk."""
    return strategy_memory_registry.create(
        backend=backend,
        persist_path=persist_path,
        **backend_options,
    )


def create_trust_ledger(
    *,
    backend: str = "memory",
    persist_path: str | Path | None = None,
    **backend_options: Any,
) -> TrustLedgerBackend:
    """Create a trust ledger, optionally persisted to disk."""
    return trust_ledger_registry.create(
        backend=backend,
        persist_path=persist_path,
        **backend_options,
    )


def create_improvement_runtime(
    *,
    persist_dir: str | Path | None = None,
    strategy_filename: str = "strategy_memory.json",
    trust_filename: str = "trust_ledger.json",
    strategy_backend: str = "memory",
    trust_backend: str = "memory",
    loop_backend: str = "default",
    strategy_options: dict[str, Any] | None = None,
    trust_options: dict[str, Any] | None = None,
    loop_options: dict[str, Any] | None = None,
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

    strategy_memory = create_strategy_memory(
        backend=strategy_backend,
        persist_path=strategy_path,
        **(strategy_options or {}),
    )
    trust_ledger = create_trust_ledger(
        backend=trust_backend,
        persist_path=trust_path,
        **(trust_options or {}),
    )
    loop = create_self_improvement_loop(
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        backend=loop_backend,
        quality_threshold=quality_threshold,
        **(loop_options or {}),
    )
    return ImprovementRuntime(
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        loop=loop,
    )


def _ensure_json_array_file(path: Path) -> None:
    if not path.exists():
        path.write_text("[]", encoding="utf-8")
