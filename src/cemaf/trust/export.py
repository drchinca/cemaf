"""Helpers for exporting CEMAF trust-ledger artifacts to disk."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cemaf.core.utils import safe_json


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_json(payload), indent=2), encoding="utf-8")


@dataclass(frozen=True)
class TrustLedgerBundle:
    """Serialized trust-ledger entries written to disk."""

    entries: list[dict[str, Any]]


def snapshot_trust_entries(*, trust_ledger: Any) -> list[dict[str, Any]]:
    """Return the current trust-ledger entries as plain dictionaries."""

    return [asdict(entry) for entry in trust_ledger.list_all()]


def export_trust_ledger(
    *,
    root: str | Path,
    trust_ledger: Any,
    path: str = "trust_ledger.json",
) -> TrustLedgerBundle:
    """Write the current trust ledger under ``root``."""

    entries = snapshot_trust_entries(trust_ledger=trust_ledger)
    _write_json(Path(root) / path, entries)
    return TrustLedgerBundle(entries=entries)
