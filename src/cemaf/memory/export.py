"""Helpers for exporting snapshots from CEMAF memory surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cemaf.core.enums import MemoryScope
from cemaf.core.utils import safe_json


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_json(payload), indent=2), encoding="utf-8")


@dataclass(frozen=True)
class MemorySnapshotBundle:
    """Resolved snapshot of promoted memory items written to disk."""

    items: list[dict[str, Any]]


async def snapshot_promoted_items(
    *,
    memory_manager: Any,
    promoted_items: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Resolve promoted memory references into their current stored values."""

    if memory_manager is None or not promoted_items:
        return []

    snapshot: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for promoted in promoted_items:
        scope_value = str(promoted.get("scope", "")).strip()
        key = str(promoted.get("key", "")).strip()
        if not scope_value or not key:
            continue
        marker = (scope_value, key)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            scope = MemoryScope(scope_value)
        except ValueError:
            continue
        item = await memory_manager.recall_by_key(scope, key)
        if item is None:
            continue
        snapshot.append(
            {
                "scope": item.scope.value,
                "key": item.key,
                "confidence": float(item.confidence),
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
                "value": safe_json(item.value),
            }
        )
    return snapshot


async def export_memory_snapshot(
    *,
    root: str | Path,
    memory_manager: Any,
    promoted_items: list[dict[str, str]],
    path: str = "learning_memory_snapshot.json",
) -> MemorySnapshotBundle:
    """Resolve promoted items and write them as a snapshot under ``root``."""

    items = await snapshot_promoted_items(
        memory_manager=memory_manager,
        promoted_items=promoted_items,
    )
    _write_json(Path(root) / path, items)
    return MemorySnapshotBundle(items=items)
