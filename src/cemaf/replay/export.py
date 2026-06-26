"""Helpers for serializing replay results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cemaf.core.utils import safe_json
from cemaf.replay.replayer import ReplayResult


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_json(payload), indent=2), encoding="utf-8")


@dataclass(frozen=True)
class ReplayArtifactsBundle:
    """Serialized replay result written to disk."""

    payload: dict[str, Any]


def replay_result_payload(result: ReplayResult) -> dict[str, Any]:
    """Serialize a replay result into a durable JSON payload."""

    return {
        "success": result.success,
        "mode": result.mode.value,
        "duration_ms": result.duration_ms,
        "patches_applied": result.patches_applied,
        "tools_replayed": result.tools_replayed,
        "divergences": list(result.divergences),
        "error": result.error,
        "final_context": result.final_context.to_dict(),
    }


def export_replay_artifact(
    *,
    root: str | Path,
    result: ReplayResult,
    path: str,
) -> ReplayArtifactsBundle:
    """Write a serialized replay result under ``root``."""

    payload = replay_result_payload(result)
    _write_json(Path(root) / path, payload)
    return ReplayArtifactsBundle(payload=payload)
