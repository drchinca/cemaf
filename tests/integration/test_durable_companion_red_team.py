"""Negative assurance: destructive scenarios must all survive."""

from __future__ import annotations

from pathlib import Path

from benchmarks.red_team_durable_companion import run_red_team


def test_red_team_survives_kill_race_and_interrupted_writes(tmp_path: Path) -> None:
    result = run_red_team(tmp_path)

    assert result["results"]["single_owner_sigkill_recovery"]["status"] == "SURVIVED"
    assert result["results"]["single_owner_sigkill_recovery"]["durable_trace_replay"] is True

    assert result["overall"] == "SURVIVED"
    assert result["broken_invariants"] == []
    assert result["results"]["duplicate_resume_exactly_once"]["status"] == "SURVIVED"
    assert result["results"]["duplicate_resume_exactly_once"]["external_side_effects"] == 1
    assert result["results"]["interrupted_checkpoint_write"]["status"] == "SURVIVED"
    assert result["results"]["interrupted_trace_write"]["status"] == "SURVIVED"
    assert result["results"]["interrupted_effect_write"]["status"] == "SURVIVED"
