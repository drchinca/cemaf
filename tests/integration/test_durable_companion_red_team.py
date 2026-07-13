"""Negative assurance: prove the red-team harness detects real gaps."""

from __future__ import annotations

from pathlib import Path

from benchmarks.red_team_durable_companion import run_red_team


def test_red_team_separates_real_recovery_from_unsafe_durability_claims(tmp_path: Path) -> None:
    result = run_red_team(tmp_path)

    assert result["results"]["single_owner_sigkill_recovery"]["status"] == "SURVIVED"
    assert result["results"]["single_owner_sigkill_recovery"]["durable_trace_replay"] is True

    assert result["overall"] == "BROKEN"
    assert result["results"]["duplicate_resume_exactly_once"]["status"] == "BROKEN"
    assert result["results"]["duplicate_resume_exactly_once"]["external_side_effects"] > 1
    assert result["results"]["interrupted_checkpoint_write"]["status"] == "BROKEN"
    assert result["results"]["interrupted_trace_write"]["status"] == "BROKEN"
