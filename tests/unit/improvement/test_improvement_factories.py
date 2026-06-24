"""Tests for self-improvement factory helpers."""

from __future__ import annotations

from pathlib import Path

from cemaf.improvement import create_improvement_runtime, create_self_improvement_loop
from cemaf.memory.strategy import StrategyMemory
from cemaf.trust.ledger import TrustLedger


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


def test_create_improvement_runtime_persists_components(tmp_path: Path) -> None:
    runtime = create_improvement_runtime(persist_dir=tmp_path / "improvement")

    assert (tmp_path / "improvement" / "strategy_memory.json").exists()
    assert (tmp_path / "improvement" / "trust_ledger.json").exists()
    assert runtime.loop is not None
    assert runtime.loop._strategy_memory is runtime.strategy_memory
    assert runtime.loop._trust_ledger is runtime.trust_ledger
