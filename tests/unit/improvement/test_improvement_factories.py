"""Tests for self-improvement factory helpers."""

from __future__ import annotations

from pathlib import Path

from cemaf.improvement import create_improvement_runtime


def test_create_improvement_runtime_persists_components(tmp_path: Path) -> None:
    runtime = create_improvement_runtime(persist_dir=tmp_path / "improvement")

    assert (tmp_path / "improvement" / "strategy_memory.json").exists()
    assert (tmp_path / "improvement" / "trust_ledger.json").exists()
    assert runtime.loop is not None
    assert runtime.loop._strategy_memory is runtime.strategy_memory
    assert runtime.loop._trust_ledger is runtime.trust_ledger
