"""Durable file-backed checkpoint storage for DAG execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cemaf.context.context import Context
from cemaf.core.enums import RunStatus
from cemaf.core.types import NodeID, RunID
from cemaf.orchestration.checkpointer import DAGCheckpoint
from cemaf.persistence.atomic_file import atomic_write_text, process_file_lock


class StaleCheckpointWriteError(RuntimeError):
    """A lower fencing token attempted to overwrite a newer checkpoint."""


def checkpoint_to_dict(checkpoint: DAGCheckpoint) -> dict[str, Any]:
    """Serialize a DAGCheckpoint to a JSON-safe dictionary."""
    return {
        "run_id": str(checkpoint.run_id),
        "dag_name": checkpoint.dag_name,
        "status": checkpoint.status.value,
        "completed_nodes": [str(node_id) for node_id in checkpoint.completed_nodes],
        "pending_nodes": [str(node_id) for node_id in checkpoint.pending_nodes],
        "context": checkpoint.context.to_checkpoint_dict(),
        "error": checkpoint.error,
        "failed_node": str(checkpoint.failed_node) if checkpoint.failed_node else None,
        "fencing_token": checkpoint.fencing_token,
    }


def checkpoint_from_dict(payload: dict[str, Any]) -> DAGCheckpoint:
    """Deserialize a DAGCheckpoint from a JSON dictionary."""
    return DAGCheckpoint(
        run_id=RunID(payload["run_id"]),
        dag_name=payload["dag_name"],
        status=RunStatus(payload["status"]),
        completed_nodes=tuple(NodeID(node_id) for node_id in payload.get("completed_nodes", [])),
        pending_nodes=tuple(NodeID(node_id) for node_id in payload.get("pending_nodes", [])),
        context=Context.from_checkpoint_dict(payload.get("context", {})),
        error=payload.get("error"),
        failed_node=NodeID(payload["failed_node"]) if payload.get("failed_node") else None,
        fencing_token=int(payload.get("fencing_token", 0)),
    )


class FileCheckpointer:
    """Persist DAG checkpoints as JSON files under a root directory.

    Checkpoints are keyed per run (`{run_id}.json`), so a single run overwrites its
    own file. Across runs the directory would grow unbounded, so retention is capped:
    after each save, all but the `max_checkpoints` most-recent run files are pruned.
    Set `max_checkpoints=0` to disable pruning (keep everything).
    """

    def __init__(self, root: str | Path, *, max_checkpoints: int = 5) -> None:
        if max_checkpoints < 0:
            raise ValueError("max_checkpoints must be >= 0 (0 disables pruning)")
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_checkpoints = max_checkpoints

    def _path_for(self, run_id: RunID) -> Path:
        safe = str(run_id).replace(":", "-").replace("/", "-")
        return self._root / f"{safe}.json"

    async def save(self, checkpoint: DAGCheckpoint) -> None:
        path = self._path_for(checkpoint.run_id)
        with process_file_lock(path.with_suffix(path.suffix + ".lock")):
            existing = await self.load(checkpoint.run_id)
            if existing is not None and checkpoint.fencing_token < existing.fencing_token:
                raise StaleCheckpointWriteError(
                    f"checkpoint token {checkpoint.fencing_token} is older than "
                    f"{existing.fencing_token} for run {checkpoint.run_id}"
                )
            atomic_write_text(
                path,
                json.dumps(checkpoint_to_dict(checkpoint), indent=2),
            )
        self._prune()

    def _prune(self) -> None:
        """Delete oldest run checkpoint files beyond the retention cap (newest kept)."""
        if self._max_checkpoints <= 0:
            return
        # Sort newest-first by mtime; tie-break on name so equal-mtime files (common
        # in fast loops / coarse fs clocks) prune deterministically.
        files = sorted(
            self._root.glob("*.json"),
            key=lambda p: (p.stat().st_mtime, p.name),
            reverse=True,
        )
        for stale in files[self._max_checkpoints :]:
            stale.unlink(missing_ok=True)

    async def load(self, run_id: RunID) -> DAGCheckpoint | None:
        path = self._path_for(run_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return checkpoint_from_dict(payload)

    async def delete(self, run_id: RunID) -> bool:
        path = self._path_for(run_id)
        if not path.is_file():
            return False
        path.unlink()
        return True
