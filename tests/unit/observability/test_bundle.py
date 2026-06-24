from __future__ import annotations

import json
from pathlib import Path

import pytest

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchSource
from cemaf.core.enums import RunStatus
from cemaf.observability.bundle import export_standard_run_artifacts, inspect_bundle_record_path
from cemaf.observability.run_logger import LLMCall, RunRecord
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.results import ExecutionResult, NodeResult


@pytest.mark.asyncio
async def test_export_standard_run_artifacts_writes_common_bundle_files(tmp_path: Path) -> None:
    asset = tmp_path / "source.png"
    asset.write_bytes(b"png-bytes")
    asset_record = {
        "asset": {
            "id": "asset-1",
            "storage_ref": str(asset),
            "state": "pending_review",
        }
    }
    final_context = Context(
        data={
            "STEP_1_OUTPUT": {"topic_analysis": "calm content"},
            "STEP_3_5_OUTPUT": {"asset_refs": [str(asset)], "assets": [asset_record]},
        }
    )
    dag = (
        DAG(name="content_static_post_instagram", description="demo")
        .add_node(
            Node.agent(
                id="research",
                name="Research",
                agent_id="research",
                input_mapping={"prompt": "x"},
                output_key="STEP_1_OUTPUT",
            )
        )
        .add_node(
            Node.agent(
                id="image_gen",
                name="Image",
                agent_id="image_synthesis",
                input_mapping={"scene": "x"},
                output_key="STEP_3_5_OUTPUT",
            )
        )
    )
    result = ExecutionResult(
        run_id="run:test/standard-bundle",
        dag_name=dag.name,
        status=RunStatus.COMPLETED,
        node_results=(
            NodeResult(node_id="research", success=True, output='{"topic_analysis":"calm content"}'),
            NodeResult(
                node_id="image_gen",
                success=True,
                output=json.dumps({"asset_refs": [str(asset)], "assets": [asset_record], "passed": True}),
            ),
        ),
        final_context=final_context,
    )
    record = RunRecord(
        run_id="run:test/standard-bundle",
        dag_name=dag.name,
        initial_context=Context(data={"prompt": "x"}),
        final_context=final_context,
        patches=[
            ContextPatch.set(
                path="STEP_1_OUTPUT",
                value={"topic_analysis": "calm content"},
                source=PatchSource.AGENT,
                source_id="research",
                reason="Output from node 'research'",
            )
        ],
        llm_calls=[
            LLMCall(
                model="gpt-4o-mini",
                input_messages=[{"role": "user", "content": "prompt"}],
                output='{"topic_analysis":"calm content"}',
                input_tokens=10,
                output_tokens=5,
                node_id="research",
                agent_id="research",
            )
        ],
        completed_at=result.completed_at,
    )

    bundle = await export_standard_run_artifacts(
        root=tmp_path / "bundle",
        dag=dag,
        result=result,
        record=record,
        configured={"llm_provider": "openai", "model": "gpt-4o-mini"},
    )

    root = tmp_path / "bundle"
    assert (root / "dag.json").is_file()
    assert (root / "execution_result.json").is_file()
    assert (root / "asset_records.json").is_file()
    assert (root / "assets" / "manifest.json").is_file()
    assert (root / "run_record.json").is_file()
    assert (root / "glass_box_report.json").is_file()
    assert (root / "replay.patch_only.json").is_file()
    assert (root / "models.json").is_file()
    assert bundle.run_record is not None
    assert len(bundle.execution.node_index) == 2
    assert len(bundle.assets.records) == 1
    assert len(bundle.llm_calls) == 1
    assert len(bundle.checkpoint_index) == 2
    assert bundle.model_usage.payload["configured"]["model"] == "gpt-4o-mini"
    assert bundle.replay_patch_only is not None


@pytest.mark.asyncio
async def test_inspect_bundle_record_path_loads_common_bundle_artifacts(tmp_path: Path) -> None:
    asset = tmp_path / "source.png"
    asset.write_bytes(b"png-bytes")
    final_context = Context(data={"STEP_1_OUTPUT": {"topic_analysis": "calm content"}})
    dag = DAG(name="content_static_post_instagram", description="demo").add_node(
        Node.agent(
            id="research",
            name="Research",
            agent_id="research",
            input_mapping={"prompt": "x"},
            output_key="STEP_1_OUTPUT",
        )
    )
    result = ExecutionResult(
        run_id="run:test/inspect-bundle",
        dag_name=dag.name,
        status=RunStatus.COMPLETED,
        node_results=(
            NodeResult(node_id="research", success=True, output='{"topic_analysis":"calm content"}'),
        ),
        final_context=final_context,
    )
    record = RunRecord(
        run_id="run:test/inspect-bundle",
        dag_name=dag.name,
        initial_context=Context(data={"prompt": "x"}),
        final_context=final_context,
        patches=[
            ContextPatch.set(
                path="STEP_1_OUTPUT",
                value={"topic_analysis": "calm content"},
                source=PatchSource.AGENT,
                source_id="research",
                reason="Output from node 'research'",
            )
        ],
        completed_at=result.completed_at,
    )

    root = tmp_path / "bundle"
    await export_standard_run_artifacts(
        root=root,
        dag=dag,
        result=result,
        record=record,
        configured={},
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run:test/inspect-bundle",
                "dag_name": dag.name,
                "success": True,
                "files": {"dag_json": "dag.json"},
            }
        ),
        encoding="utf-8",
    )

    inspection = inspect_bundle_record_path(record_path=root / "run_record.json")

    assert inspection.bundle_dir == root.resolve()
    assert inspection.manifest is not None
    assert inspection.execution_result is not None
    assert inspection.run_record is not None
    assert inspection.has_node("research") is True
    assert inspection.branchable_outputs == ["STEP_1_OUTPUT"]
    assert inspection.load_checkpoint_context("STEP_1_OUTPUT").get("STEP_1_OUTPUT") == {
        "topic_analysis": "calm content"
    }
