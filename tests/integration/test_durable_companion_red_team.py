"""Negative assurance: destructive scenarios must all survive."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import patch

from benchmarks.red_team_durable_companion import _advance_fixture_clock, _worker_main, run_red_team
from cemaf.observability.run_logger import FileRunLogger


def test_slow_trace_setup_does_not_expire_the_crash_fixture_lease(tmp_path):
    _advance_fixture_clock(tmp_path)
    original = FileRunLogger.start_run

    def slow_start(logger, *args, **kwargs):
        original(logger, *args, **kwargs)
        # Regression: a 0.6-second setup expired the harness's 0.5-second lease.
        time.sleep(0.6)

    args = argparse.Namespace(
        root=str(tmp_path), run_id="slow-start", worker_id="slow-worker", action="run", mode="normal"
    )
    with patch.object(FileRunLogger, "start_run", slow_start):
        asyncio.run(_worker_main(args))
    result = json.loads((tmp_path / "result-slow-worker.json").read_text())
    assert result["status"] == "completed"


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
