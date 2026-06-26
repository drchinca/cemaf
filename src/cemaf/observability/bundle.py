"""Helpers for exporting generic CEMAF run-record bundles to disk."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from cemaf.context.context import Context
from cemaf.core.enums import RunStatus
from cemaf.core.types import RunID
from cemaf.core.utils import safe_json
from cemaf.observability.glass_box import GlassBoxReporter
from cemaf.observability.run_logger import RunRecord
from cemaf.orchestration.checkpointer import DAGCheckpoint
from cemaf.orchestration.file_checkpointer import checkpoint_from_dict, checkpoint_to_dict
from cemaf.replay.export import replay_result_payload
from cemaf.replay.replayer import Replayer, ReplayMode


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_json(payload), indent=2), encoding="utf-8")


def load_bundle_json(*, bundle_dir: str | Path, path: str) -> Any:
    """Load a JSON artifact relative to a run bundle directory."""

    return json.loads((Path(bundle_dir) / path).read_text(encoding="utf-8"))


def load_bundle_manifest(
    *,
    bundle_dir: str | Path,
    path: str = "manifest.json",
) -> dict[str, Any]:
    """Load a bundle manifest as a dictionary."""

    payload = load_bundle_json(bundle_dir=bundle_dir, path=path)
    if not isinstance(payload, dict):
        raise ValueError("Bundle manifest is malformed.")
    return payload


def load_bundle_dag_json(
    *,
    bundle_dir: str | Path,
    manifest_path: str = "manifest.json",
    default_path: str = "dag.json",
) -> dict[str, Any]:
    """Load the DAG JSON referenced by a bundle manifest."""

    manifest = load_bundle_manifest(bundle_dir=bundle_dir, path=manifest_path)
    files = manifest.get("files", {})
    dag_path = str(files.get("dag_json") or default_path) if isinstance(files, dict) else default_path
    payload = load_bundle_json(bundle_dir=bundle_dir, path=dag_path)
    if not isinstance(payload, dict):
        raise ValueError("Bundle DAG artifact is malformed.")
    return payload


def inspect_bundle(
    *,
    bundle_dir: str | Path,
    include_dag: bool = True,
    include_execution_result: bool = True,
    include_record: bool = True,
    include_checkpoints: bool = True,
) -> BundleInspection:
    """Load the common persisted artifacts present in a run bundle."""

    root = Path(bundle_dir)
    manifest: dict[str, Any] | None = None
    if (root / "manifest.json").is_file():
        loaded_manifest = load_bundle_manifest(bundle_dir=root)
        manifest = loaded_manifest if isinstance(loaded_manifest, dict) else None

    dag_payload: dict[str, Any] | None = None
    if include_dag and manifest is not None:
        try:
            loaded_dag = load_bundle_dag_json(bundle_dir=root)
        except FileNotFoundError:
            loaded_dag = None
        dag_payload = loaded_dag if isinstance(loaded_dag, dict) else None

    execution_result: dict[str, Any] | None = None
    if include_execution_result and (root / "execution_result.json").is_file():
        loaded_execution = load_bundle_json(bundle_dir=root, path="execution_result.json")
        execution_result = loaded_execution if isinstance(loaded_execution, dict) else None

    run_record = load_bundle_record(bundle_dir=root) if include_record else None

    checkpoint_index: list[dict[str, Any]] = []
    if include_checkpoints and (root / "checkpoints" / "index.json").is_file():
        loaded_index = load_bundle_json(bundle_dir=root, path="checkpoints/index.json")
        if isinstance(loaded_index, list):
            checkpoint_index = [item for item in loaded_index if isinstance(item, dict)]

    return BundleInspection(
        bundle_dir=root,
        manifest=manifest,
        dag_payload=dag_payload,
        execution_result=execution_result,
        run_record=run_record,
        checkpoint_index=checkpoint_index,
    )


def bundle_has_node(*, bundle_dir: str | Path, node_id: str) -> bool:
    """Return whether a persisted bundle DAG includes the given node ID."""

    dag_payload = load_bundle_dag_json(bundle_dir=bundle_dir)
    nodes = dag_payload.get("nodes", [])
    if not isinstance(nodes, list):
        return False
    return any(str(node.get("id", "")) == node_id for node in nodes if isinstance(node, dict))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "run"


def compact_slug(value: str, *, max_length: int = 40) -> str:
    """Create a short hyphenated label safe for human-facing bundle names."""

    words = re.findall(r"[A-Za-z0-9]+", value.lower())
    slug = "-".join(words) or "run"
    return slug[:max_length].strip("-") or "run"


def short_token(value: str, *, length: int = 6) -> str:
    """Return a short stable token derived from a string value."""

    return sha256(value.encode("utf-8")).hexdigest()[:length]


def timestamp_label(*, run_id: str, fallback: datetime | None = None) -> str:
    """Extract a stable timestamp label from a run ID or fallback time."""

    match = re.search(r"run_(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})", run_id)
    if match:
        return f"{match.group(1)}_{match.group(2)}{match.group(3)}{match.group(4)}"
    if fallback is not None:
        return fallback.strftime("%Y-%m-%d_%H%M%S")
    return "undated"


def live_run_dir_name(*, run_id: str, label: str) -> str:
    """Build a human-friendly live run directory name."""

    return "__".join(
        [
            "live",
            timestamp_label(run_id=run_id),
            compact_slug(label, max_length=28),
            short_token(run_id),
        ]
    )


def artifact_bundle_dir_name(
    *,
    run_id: str,
    started_at: datetime | None,
    labels: list[str],
    prompt: str,
) -> str:
    """Build a durable, human-friendly artifact bundle directory name."""

    prompt_label = compact_slug(prompt, max_length=36) if prompt.strip() else "untitled"
    return "__".join(
        [
            timestamp_label(run_id=run_id, fallback=started_at),
            *[compact_slug(label, max_length=28) for label in labels if label.strip()],
            prompt_label,
            short_token(run_id),
        ]
    )


def _checkpoint_payload(
    *,
    record: RunRecord,
    context: Context,
    status: RunStatus,
) -> dict[str, Any]:
    return checkpoint_to_dict(
        DAGCheckpoint(
            run_id=RunID(record.run_id),
            dag_name=record.dag_name,
            status=status,
            completed_nodes=(),
            pending_nodes=(),
            context=context,
        )
    )


@dataclass(frozen=True)
class RunRecordBundle:
    """Generic CEMAF run-record artifacts written to a bundle directory."""

    llm_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    patches: list[dict[str, Any]]
    provenance_chain: dict[str, Any] | None
    glass_box_report: dict[str, Any]
    replay_patch_only: dict[str, Any]
    checkpoint_index: list[dict[str, Any]]


@dataclass(frozen=True)
class ExecutionArtifactsBundle:
    """Generic DAG/execution artifacts written to a bundle directory."""

    execution_result: dict[str, Any]
    node_index: list[dict[str, Any]]


@dataclass(frozen=True)
class FileEvidenceBundle:
    """Copied file evidence plus a manifest written under a bundle directory."""

    manifest: list[dict[str, Any]]


@dataclass(frozen=True)
class AssetArtifactsBundle:
    """Exported asset records plus copied-file evidence written under a bundle directory."""

    manifest: list[dict[str, Any]]
    records: list[dict[str, Any]]


@dataclass(frozen=True)
class ModelUsageBundle:
    """Observed model usage summary written to a bundle directory."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class BundleManifestBundle:
    """Top-level bundle manifest written to a bundle directory."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class BundleInspection:
    """Loaded run-bundle artifacts used by branching, replay, and offline analysis."""

    bundle_dir: Path
    manifest: dict[str, Any] | None = None
    dag_payload: dict[str, Any] | None = None
    execution_result: dict[str, Any] | None = None
    run_record: RunRecord | None = None
    checkpoint_index: list[dict[str, Any]] = field(default_factory=list)

    @property
    def branchable_outputs(self) -> list[str]:
        return branchable_outputs(self.checkpoint_index)

    def has_node(self, node_id: str) -> bool:
        """Return whether the loaded DAG payload contains the given node."""
        if not isinstance(self.dag_payload, dict):
            return False
        nodes = self.dag_payload.get("nodes", [])
        if not isinstance(nodes, list):
            return False
        return any(str(node.get("id", "")) == node_id for node in nodes if isinstance(node, dict))

    def load_checkpoint_context(self, checkpoint_key: str) -> Context:
        """Load a checkpoint context from this bundle by logical context path."""
        return load_bundle_checkpoint_context(
            bundle_dir=self.bundle_dir,
            checkpoint_key=checkpoint_key,
        )


@dataclass(frozen=True)
class StandardRunArtifactsBundle:
    """Standard generic run-artifact set exported under a bundle directory."""

    execution: ExecutionArtifactsBundle
    assets: AssetArtifactsBundle
    run_record: RunRecordBundle | None
    model_usage: ModelUsageBundle
    llm_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    patches: list[dict[str, Any]]
    replay_patch_only: dict[str, Any] | None
    checkpoint_index: list[dict[str, Any]]


def parse_artifact_output(value: Any) -> tuple[str, Any]:
    if isinstance(value, str):
        try:
            return "json", json.loads(value)
        except json.JSONDecodeError:
            return "txt", value
    return "json", safe_json(value)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def iter_bundle_dirs(*, runs_dir: str | Path) -> list[Path]:
    """Return run-bundle directories under ``runs_dir`` that contain a manifest."""

    manifests = sorted(Path(runs_dir).glob("*/manifest.json"))
    return [path.parent for path in manifests]


def bundle_dir_from_record_path(record_path: str | Path) -> Path:
    """Resolve the bundle directory from a ``run_record.json`` path."""

    path = Path(record_path).resolve()
    if path.name != "run_record.json":
        raise ValueError("Expected --record to point at a run_record.json file.")
    return path.parent


def inspect_bundle_record_path(
    *,
    record_path: str | Path,
    include_dag: bool = True,
    include_execution_result: bool = True,
    include_record: bool = True,
    include_checkpoints: bool = True,
) -> BundleInspection:
    """Resolve a ``run_record.json`` path and inspect its parent bundle."""

    return inspect_bundle(
        bundle_dir=bundle_dir_from_record_path(record_path),
        include_dag=include_dag,
        include_execution_result=include_execution_result,
        include_record=include_record,
        include_checkpoints=include_checkpoints,
    )


def load_bundle_record(*, bundle_dir: str | Path, path: str = "run_record.json") -> RunRecord | None:
    """Load a persisted ``RunRecord`` from a bundle if present."""

    record_path = Path(bundle_dir) / path
    if not record_path.is_file():
        return None
    payload = load_bundle_json(bundle_dir=bundle_dir, path=path)
    if not isinstance(payload, dict):
        return None
    try:
        return RunRecord.from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None


def load_bundle_checkpoint_context(*, bundle_dir: str | Path, checkpoint_key: str) -> Context:
    """Load a checkpoint context from a bundle by logical context path.

    Supports both the new CEMAF ``DAGCheckpoint`` payloads and legacy
    context-only checkpoint files.
    """

    checkpoint_index = load_bundle_json(bundle_dir=bundle_dir, path="checkpoints/index.json")
    if not isinstance(checkpoint_index, list):
        raise ValueError("Checkpoint index is malformed.")

    matched_path: str | None = None
    for item in reversed(checkpoint_index):
        if str(item.get("context_path", "")) == checkpoint_key:
            matched_path = str(item.get("path", "") or "")
            break
    if not matched_path:
        raise ValueError(f"Checkpoint key '{checkpoint_key}' was not found in bundle.")

    payload = load_bundle_json(bundle_dir=bundle_dir, path=matched_path)
    if isinstance(payload, dict) and {"run_id", "dag_name", "status", "context"} <= payload.keys():
        return checkpoint_from_dict(payload).context
    return Context.from_checkpoint_dict(payload)


def branchable_outputs(checkpoint_index: list[dict[str, Any]]) -> list[str]:
    """Return unique ``STEP_*`` context outputs from a checkpoint index."""

    seen: list[str] = []
    for item in checkpoint_index:
        path = str(item.get("context_path", "") or "")
        if path.startswith("STEP_") and path not in seen:
            seen.append(path)
    return seen


def node_duration_map(node_results: tuple[Any, ...]) -> dict[str, float]:
    """Summarize per-node execution durations."""

    return {
        str(node_result.node_id): round(float(node_result.duration_ms or 0.0), 3)
        for node_result in node_results
    }


def node_recall_counts(node_results: tuple[Any, ...]) -> dict[str, int]:
    """Summarize recalled-memory counts by node."""

    counts: dict[str, int] = {}
    for node_result in node_results:
        metadata = node_result.metadata or {}
        recall_count = metadata.get("recalled_memory_count", 0) if isinstance(metadata, dict) else 0
        try:
            counts[str(node_result.node_id)] = int(recall_count or 0)
        except (TypeError, ValueError):
            counts[str(node_result.node_id)] = 0
    return counts


def node_model_map(llm_calls: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Summarize observed models by node or agent ID."""

    mapping: dict[str, list[str]] = {}
    for call in llm_calls:
        node_id = str(call.get("node_id") or call.get("agent_id") or "").strip()
        model = str(call.get("model") or "").strip()
        if not node_id or not model:
            continue
        models = mapping.setdefault(node_id, [])
        if model not in models:
            models.append(model)
    return mapping


def node_output_payload(
    node_results: tuple[Any, ...],
    *,
    node_id: str | tuple[str, ...],
) -> dict[str, Any] | None:
    """Return the parsed JSON payload for the first matching node result."""

    node_ids = (node_id,) if isinstance(node_id, str) else node_id
    for node_result in node_results:
        if str(node_result.node_id) not in node_ids:
            continue
        _, parsed_output = parse_artifact_output(node_result.output)
        if isinstance(parsed_output, dict):
            return parsed_output
        return None
    return None


def _node_result_dict(result: Any) -> dict[str, Any]:
    return {
        "node_id": str(result.node_id),
        "success": result.success,
        "output": safe_json(result.output),
        "error": result.error,
        "duration_ms": result.duration_ms,
        "metadata": safe_json(result.metadata),
    }


def _execution_result_dict(result: Any) -> dict[str, Any]:
    return {
        "run_id": str(result.run_id),
        "dag_name": result.dag_name,
        "status": result.status.value,
        "success": result.success,
        "error": result.error,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "duration_ms": result.duration_ms,
        "metadata": safe_json(result.metadata),
        "health_check_metadata": safe_json(result.health_check_metadata),
        "node_results": [_node_result_dict(node) for node in result.node_results],
    }


async def export_execution_artifacts(
    *,
    root: str | Path,
    dag: Any,
    result: Any,
) -> ExecutionArtifactsBundle:
    """Write generic DAG/execution artifacts under ``root``."""

    run_dir = Path(root)
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_json(run_dir / "dag.json", dag.to_dict())
    _write_text(run_dir / "dag.mmd", dag.to_mermaid())
    execution_result = _execution_result_dict(result)
    _write_json(run_dir / "execution_result.json", execution_result)
    _write_json(run_dir / "final_context.json", result.final_context.to_dict())
    _write_json(
        run_dir / "final_context.checkpoint.json",
        result.final_context.to_checkpoint_dict(),
    )

    node_map = {str(node.id): node for node in dag.nodes}
    node_index: list[dict[str, Any]] = []
    outputs_dir = run_dir / "nodes"
    for idx, node_result in enumerate(result.node_results, start=1):
        node_id = str(node_result.node_id)
        prefix = f"{idx:03d}_{_slug(node_id)}"
        output_kind, parsed_output = parse_artifact_output(node_result.output)
        output_name = f"{prefix}.output.{output_kind}"
        metadata_name = f"{prefix}.metadata.json"
        summary_name = f"{prefix}.json"

        if output_kind == "json":
            _write_json(outputs_dir / output_name, parsed_output)
        else:
            _write_text(outputs_dir / output_name, str(parsed_output))
        _write_json(outputs_dir / metadata_name, safe_json(node_result.metadata))

        node_payload = {
            "node_id": node_id,
            "success": node_result.success,
            "error": node_result.error,
            "duration_ms": node_result.duration_ms,
            "node_type": getattr(getattr(node_map.get(node_id), "type", None), "value", None),
            "agent_id": getattr(node_map.get(node_id), "ref_id", None),
            "output_file": f"nodes/{output_name}",
            "metadata_file": f"nodes/{metadata_name}",
        }
        _write_json(outputs_dir / summary_name, node_payload)
        node_index.append(node_payload)
    _write_json(outputs_dir / "index.json", node_index)

    return ExecutionArtifactsBundle(
        execution_result=execution_result,
        node_index=node_index,
    )


def export_file_evidence(
    *,
    root: str | Path,
    refs: list[dict[str, Any]],
    files_subdir: str = "assets/files",
    manifest_path: str = "assets/manifest.json",
) -> FileEvidenceBundle:
    """Copy referenced files into a bundle and emit a hash/size manifest.

    Each ref item should contain:
    - ``ref``: source file path string
    - any additional metadata to carry into the manifest entry
    """

    run_dir = Path(root)
    files_dir = run_dir / files_subdir
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(refs, start=1):
        ref = str(item.get("ref", "") or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        path = Path(ref)
        entry = {key: safe_json(value) for key, value in item.items() if key != "ref"}
        entry["original_ref"] = ref
        entry["exists"] = path.is_file()
        if not path.is_file():
            manifest.append(entry)
            continue
        target = files_dir / f"{idx:03d}_{path.name}"
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        data = path.read_bytes()
        entry.update(
            {
                "copied_path": str(target),
                "sha256": sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
        manifest.append(entry)

    _write_json(run_dir / manifest_path, manifest)
    return FileEvidenceBundle(manifest=manifest)


def _extract_asset_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "asset_refs" and isinstance(item, list):
                refs.extend(str(ref) for ref in item if str(ref).strip())
            else:
                refs.extend(_extract_asset_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_extract_asset_refs(item))
    return refs


def _extract_asset_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "assets" and isinstance(item, list):
                records.extend(asset for asset in item if isinstance(asset, dict) and "asset" in asset)
            else:
                records.extend(_extract_asset_records(item))
    elif isinstance(value, list):
        for item in value:
            records.extend(_extract_asset_records(item))
    return records


def export_node_asset_artifacts(
    *,
    root: str | Path,
    node_results: tuple[Any, ...],
    files_subdir: str = "assets/files",
    manifest_path: str = "assets/manifest.json",
    records_path: str = "asset_records.json",
) -> AssetArtifactsBundle:
    """Export asset records and copied-file evidence discovered in node outputs."""

    run_dir = Path(root)
    asset_records: list[dict[str, Any]] = []
    seen_asset_ids: set[str] = set()
    for node_result in node_results:
        _, parsed_output = parse_artifact_output(node_result.output)
        for record in _extract_asset_records(parsed_output):
            asset = record.get("asset", {})
            asset_id = str(asset.get("id", "") or "")
            if not asset_id or asset_id in seen_asset_ids:
                continue
            seen_asset_ids.add(asset_id)
            asset_records.append(record)

    _write_json(run_dir / records_path, asset_records)

    asset_index: dict[str, dict[str, Any]] = {}
    for record in asset_records:
        asset = record.get("asset", {})
        if not isinstance(asset, dict):
            continue
        ref = str(asset.get("storage_ref", "") or "").strip()
        if ref:
            asset_index[ref] = record

    refs: list[dict[str, Any]] = []
    for node_result in node_results:
        _, parsed_output = parse_artifact_output(node_result.output)
        for ref in _extract_asset_refs(parsed_output):
            entry: dict[str, Any] = {
                "node_id": str(node_result.node_id),
                "ref": ref,
            }
            asset_record = asset_index.get(ref)
            if asset_record is not None:
                entry["asset_record"] = asset_record
            refs.append(entry)

    manifest = export_file_evidence(
        root=run_dir,
        refs=refs,
        files_subdir=files_subdir,
        manifest_path=manifest_path,
    ).manifest
    return AssetArtifactsBundle(manifest=manifest, records=asset_records)


def export_model_usage(
    *,
    root: str | Path,
    llm_calls: list[dict[str, Any]],
    node_index: list[dict[str, Any]],
    configured: dict[str, Any] | None = None,
    path: str = "models.json",
) -> ModelUsageBundle:
    """Write aggregated observed-model usage under ``root``."""

    by_model: dict[str, dict[str, Any]] = {}
    for call in llm_calls:
        model = str(call.get("model", "") or "").strip()
        if not model:
            continue
        stats = by_model.setdefault(
            model,
            {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "agents": set(),
                "nodes": set(),
            },
        )
        stats["calls"] += 1
        stats["input_tokens"] += int(call.get("input_tokens", 0) or 0)
        stats["output_tokens"] += int(call.get("output_tokens", 0) or 0)
        stats["cost_usd"] += float(call.get("cost_usd", 0.0) or 0.0)
        if call.get("agent_id"):
            stats["agents"].add(str(call["agent_id"]))
        if call.get("node_id"):
            stats["nodes"].add(str(call["node_id"]))

    payload = {
        "configured": safe_json(configured or {}),
        "observed_models": {
            model: {
                "calls": stats["calls"],
                "input_tokens": stats["input_tokens"],
                "output_tokens": stats["output_tokens"],
                "cost_usd": round(stats["cost_usd"], 6),
                "agents": sorted(stats["agents"]),
                "nodes": sorted(stats["nodes"]),
            }
            for model, stats in by_model.items()
        },
        "nodes": node_index,
    }
    _write_json(Path(root) / path, payload)
    return ModelUsageBundle(payload=payload)


def export_bundle_manifest(
    *,
    root: str | Path,
    payload: dict[str, Any],
    path: str = "manifest.json",
) -> BundleManifestBundle:
    """Write a top-level bundle manifest under ``root``."""

    manifest = safe_json(payload)
    _write_json(Path(root) / path, manifest)
    return BundleManifestBundle(payload=manifest)


async def export_standard_run_artifacts(
    *,
    root: str | Path,
    dag: Any,
    result: Any,
    record: RunRecord | None = None,
    configured: dict[str, Any] | None = None,
) -> StandardRunArtifactsBundle:
    """Export the standard generic run-artifact set used by downstream apps.

    This helper composes the common CEMAF export surfaces for:
    - DAG/execution artifacts
    - copied asset evidence
    - optional run-record/replay artifacts
    - observed model-usage summaries
    """

    execution = await export_execution_artifacts(
        root=root,
        dag=dag,
        result=result,
    )
    assets = export_node_asset_artifacts(root=root, node_results=result.node_results)

    run_record_bundle: RunRecordBundle | None = None
    llm_calls: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    patches: list[dict[str, Any]] = []
    replay_patch_only: dict[str, Any] | None = None
    checkpoint_index: list[dict[str, Any]] = []
    if record is not None:
        run_record_bundle = await export_run_record_bundle(root=root, record=record)
        llm_calls = run_record_bundle.llm_calls
        tool_calls = run_record_bundle.tool_calls
        patches = run_record_bundle.patches
        replay_patch_only = run_record_bundle.replay_patch_only
        checkpoint_index = run_record_bundle.checkpoint_index

    model_usage = export_model_usage(
        root=root,
        llm_calls=llm_calls,
        node_index=execution.node_index,
        configured=configured,
    )

    return StandardRunArtifactsBundle(
        execution=execution,
        assets=assets,
        run_record=run_record_bundle,
        model_usage=model_usage,
        llm_calls=llm_calls,
        tool_calls=tool_calls,
        patches=patches,
        replay_patch_only=replay_patch_only,
        checkpoint_index=checkpoint_index,
    )


async def export_run_record_bundle(*, root: str | Path, record: RunRecord) -> RunRecordBundle:
    """Write the generic CEMAF run-record artifact set under ``root``."""

    run_dir = Path(root)
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_json(run_dir / "run_record.json", record.to_dict())

    llm_calls = [call.to_dict() for call in record.llm_calls]
    tool_calls = [call.to_dict() for call in record.tool_calls]
    patches = [patch.to_dict() for patch in record.patches]
    provenance_chain = record.provenance_chain.to_dict() if record.provenance_chain else None

    _write_json(run_dir / "llm_calls.json", llm_calls)
    _write_json(run_dir / "tool_calls.json", tool_calls)
    _write_json(run_dir / "patches.json", patches)
    if provenance_chain is not None:
        _write_json(run_dir / "provenance_chain.json", provenance_chain)

    glass_box = GlassBoxReporter().generate(record).to_dict()
    _write_json(run_dir / "glass_box_report.json", glass_box)

    replay_result = await Replayer(record).replay(mode=ReplayMode.PATCH_ONLY)
    replay_payload = replay_result_payload(replay_result)
    _write_json(run_dir / "replay.patch_only.json", replay_payload)

    checkpoints_dir = run_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_index: list[dict[str, Any]] = []

    if record.initial_context is not None:
        _write_json(
            checkpoints_dir / "000_initial.json",
            _checkpoint_payload(
                record=record,
                context=record.initial_context,
                status=RunStatus.PENDING,
            ),
        )
        checkpoint_index.append(
            {
                "sequence": 0,
                "path": "checkpoints/000_initial.json",
                "source_id": "initial_context",
                "patch_id": None,
            }
        )

    ctx = record.initial_context or Context()
    for seq, patch in enumerate(record.patches, start=1):
        ctx = ctx.apply(patch)
        name = f"{seq:03d}_{_slug(patch.source_id)}_{_slug(patch.path)}.json"
        rel = f"checkpoints/{name}"
        _write_json(
            checkpoints_dir / name,
            _checkpoint_payload(
                record=record,
                context=ctx,
                status=RunStatus.RUNNING,
            ),
        )
        checkpoint_index.append(
            {
                "sequence": seq,
                "path": rel,
                "patch_id": patch.id,
                "source_id": patch.source_id,
                "context_path": patch.path,
                "operation": patch.operation.value,
                "reason": patch.reason,
                "timestamp": patch.timestamp.isoformat(),
            }
        )

    _write_json(checkpoints_dir / "index.json", checkpoint_index)

    _write_json(
        run_dir / "run_summary.json",
        {
            "run_id": record.run_id,
            "dag_name": record.dag_name,
            "success": record.success,
            "error": record.error,
            "started_at": record.started_at.isoformat(),
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "duration_ms": record.duration_ms,
            "total_tokens": record.total_tokens,
            "total_cost_usd": record.total_cost_usd,
            "total_llm_calls": record.total_llm_calls,
            "total_tool_calls": record.total_tool_calls,
            "total_patches": record.total_patches,
        },
    )

    return RunRecordBundle(
        llm_calls=llm_calls,
        tool_calls=tool_calls,
        patches=patches,
        provenance_chain=provenance_chain,
        glass_box_report=glass_box,
        replay_patch_only=replay_payload,
        checkpoint_index=checkpoint_index,
    )
