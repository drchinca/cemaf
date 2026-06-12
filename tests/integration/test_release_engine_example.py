"""The flagship release-engine example is real: its three modes work end-to-end.

Guards examples/release_engine.py — the 'what's the point of CEMAF' artifact — so
it can't silently rot. Runs produce/dry-run/wipe against a temp output dir (no
repo writes), asserting the engine threads council → auction → agent → eval →
harvest and emits the expected artifacts.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "release_engine.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("release_engine", _EXAMPLE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_example()
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path / "out")
    return module


@pytest.mark.asyncio
async def test_produce_runs_engine_and_writes_artifacts(example) -> None:
    rc = await example.produce()
    assert rc == 0

    out = example.OUTPUT_DIR
    notes = (out / "RELEASE_NOTES.md").read_text()
    report = json.loads((out / "run_report.json").read_text())

    # The whole engine threaded through one run:
    assert report["run_status"] == "completed"
    assert report["council"]["verdict"] == "ship"  # council decided
    assert report["council"]["tally"] == {"ship": 2.0, "hold": 1.0}
    assert report["auction"]["winner"] == "writer-standby"  # auction picked low-load
    # The interceptor gate RECOVERED the writer: its short first draft tripped the
    # length gate, which fed back a hint and re-ran the agent (SPEC-01a RECOVER).
    assert report["recovery"]["attempts"] == 1  # exactly one RECOVER fired
    assert report["recovery"]["writer_runs"] == 2  # stub → revised
    assert report["online_evals"] == 1  # eval ran
    assert report["blueprints_harvested"] == 1  # harvest distilled a blueprint
    assert report["cost_usd"] > 0  # budget tracked

    # The published artifact is the real council+auction product.
    assert "# Release 2.4.0" in notes
    assert "writer-standby" in notes


def test_dry_run_writes_nothing(example, capsys) -> None:
    example.dry_run()
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
    assert "council" in captured.out.lower()
    assert not example.OUTPUT_DIR.exists()  # planning touched no disk


@pytest.mark.asyncio
async def test_wipe_removes_artifacts_and_is_idempotent(example) -> None:
    await example.produce()
    assert example.OUTPUT_DIR.exists()

    example.wipe()
    assert not example.OUTPUT_DIR.exists()

    example.wipe()  # second wipe is a clean no-op
    assert not example.OUTPUT_DIR.exists()


def test_dag_shape_is_council_then_auction(example) -> None:
    dag = example.build_dag()
    ids = {str(n.id) for n in dag.nodes}
    assert ids == {"review", "write"}
    # review is a council node, write is an auction node
    review = next(n for n in dag.nodes if str(n.id) == "review")
    write = next(n for n in dag.nodes if str(n.id) == "write")
    assert "council" in review.config
    assert "capability" in write.config
