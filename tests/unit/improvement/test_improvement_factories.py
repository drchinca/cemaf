"""Tests for self-improvement factory helpers."""

from __future__ import annotations

from pathlib import Path

from cemaf.core.result import Result
from cemaf.improvement import (
    SelfImprovementProcessor,
    StrategyMemoryBackend,
    TrustLedgerBackend,
    create_improvement_runtime,
    create_self_improvement_loop,
    create_strategy_memory,
    create_trust_ledger,
    improvement_loop_registry,
    strategy_memory_registry,
    trust_ledger_registry,
)
from cemaf.improvement.loop import ExecutionSummary, ImprovementOutcome
from cemaf.memory.strategy import StrategyMemory
from cemaf.trust.ledger import TrustLedger


class FakeStrategyMemory:
    async def record_outcome(self, *args, **kwargs):
        return None

    async def get_best_strategy(self, task_pattern: str):
        return None

    async def list_strategies(self):
        return ()


class FakeTrustLedger:
    def get(self, entity_id: str):
        return None

    def record(self, entity_id: str, entity_type: str = "tool", *, success: bool, latency_ms: float = 0.0):
        return TrustLedger().record(entity_id, entity_type, success=success, latency_ms=latency_ms)


class FakeImprovementLoop:
    async def process(self, summary: ExecutionSummary):
        return Result.ok(
            ImprovementOutcome(
                run_id=summary.run_id,
                quality_score=1.0,
                strategies_updated=0,
                tools_promoted=0,
                tools_deprecated=0,
            )
        )


def test_create_self_improvement_loop_uses_supplied_dependencies() -> None:
    strategy_memory = StrategyMemory()
    trust_ledger = TrustLedger()

    loop = create_self_improvement_loop(
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        quality_threshold=0.75,
    )

    assert loop._strategy_memory is strategy_memory
    assert loop._trust_ledger is trust_ledger
    assert loop._quality_threshold == 0.75
    assert isinstance(loop, SelfImprovementProcessor)


def test_create_improvement_runtime_persists_components(tmp_path: Path) -> None:
    runtime = create_improvement_runtime(persist_dir=tmp_path / "improvement")

    assert (tmp_path / "improvement" / "strategy_memory.json").exists()
    assert (tmp_path / "improvement" / "trust_ledger.json").exists()
    assert runtime.loop is not None
    assert runtime.loop._strategy_memory is runtime.strategy_memory
    assert runtime.loop._trust_ledger is runtime.trust_ledger


def test_create_strategy_memory_uses_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return FakeStrategyMemory()

    strategy_memory_registry.register(backend="custom-test-strategy-memory", factory=_factory)

    memory = create_strategy_memory(
        backend="custom-test-strategy-memory",
        persist_path="/tmp/strategy.json",
        tenant="tenant-a",
    )

    assert isinstance(memory, StrategyMemoryBackend)
    assert created["args"]["persist_path"] == "/tmp/strategy.json"
    assert created["args"]["tenant"] == "tenant-a"


def test_create_trust_ledger_uses_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return FakeTrustLedger()

    trust_ledger_registry.register(backend="custom-test-trust-ledger", factory=_factory)

    ledger = create_trust_ledger(
        backend="custom-test-trust-ledger",
        persist_path="/tmp/trust.json",
        tenant="tenant-a",
    )

    assert isinstance(ledger, TrustLedgerBackend)
    assert created["args"]["persist_path"] == "/tmp/trust.json"
    assert created["args"]["tenant"] == "tenant-a"


def test_create_self_improvement_loop_uses_custom_registered_backend() -> None:
    created: dict[str, object] = {}
    strategy_memory = FakeStrategyMemory()
    trust_ledger = FakeTrustLedger()

    def _factory(**kwargs):
        created["args"] = kwargs
        return FakeImprovementLoop()

    improvement_loop_registry.register(backend="custom-test-improvement-loop", factory=_factory)

    loop = create_self_improvement_loop(
        strategy_memory=strategy_memory,
        trust_ledger=trust_ledger,
        backend="custom-test-improvement-loop",
        quality_threshold=0.8,
        policy="strict",
    )

    assert isinstance(loop, SelfImprovementProcessor)
    assert created["args"]["strategy_memory"] is strategy_memory
    assert created["args"]["trust_ledger"] is trust_ledger
    assert created["args"]["quality_threshold"] == 0.8
    assert created["args"]["policy"] == "strict"


def test_create_improvement_runtime_uses_registered_backends(tmp_path: Path) -> None:
    strategy_memory = FakeStrategyMemory()
    trust_ledger = FakeTrustLedger()
    loop = FakeImprovementLoop()

    strategy_memory_registry.register(
        backend="runtime-test-strategy-memory",
        factory=lambda **kwargs: strategy_memory,
    )
    trust_ledger_registry.register(
        backend="runtime-test-trust-ledger",
        factory=lambda **kwargs: trust_ledger,
    )
    improvement_loop_registry.register(
        backend="runtime-test-improvement-loop",
        factory=lambda **kwargs: loop,
    )

    runtime = create_improvement_runtime(
        persist_dir=tmp_path / "runtime",
        strategy_backend="runtime-test-strategy-memory",
        trust_backend="runtime-test-trust-ledger",
        loop_backend="runtime-test-improvement-loop",
    )

    assert runtime.strategy_memory is strategy_memory
    assert runtime.trust_ledger is trust_ledger
    assert runtime.loop is loop
