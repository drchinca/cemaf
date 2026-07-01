"""Helpers for persisting self-improvement artifacts to disk."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cemaf.core.utils import safe_json
from cemaf.improvement.loop import ImprovementOutcome


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_json(payload), indent=2), encoding="utf-8")


@dataclass(frozen=True)
class ImprovementRunReport:
    """Persistable summary of one completed self-improvement pass."""

    run_id: str
    task_pattern: str
    approach: str
    quality_score: float
    strategies_updated: int
    tools_promoted: int
    tools_deprecated: int
    insights: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImprovementReportBundle:
    """Serialized self-improvement report written to disk."""

    report: dict[str, Any]


def compose_improvement_label(**parts: object) -> str:
    """Build a stable ``key=value`` label string for strategy/improvement metadata."""

    fields: list[str] = []
    for key, value in parts.items():
        text = "unknown" if value is None else str(value).strip() or "unknown"
        fields.append(f"{key}={text}")
    return "|".join(fields)


def build_improvement_run_report(
    *,
    outcome: ImprovementOutcome,
    task_pattern: str,
    approach: str,
) -> ImprovementRunReport:
    """Attach caller-owned task metadata to a generic improvement outcome."""

    return ImprovementRunReport(
        run_id=outcome.run_id,
        task_pattern=task_pattern,
        approach=approach,
        quality_score=outcome.quality_score,
        strategies_updated=outcome.strategies_updated,
        tools_promoted=outcome.tools_promoted,
        tools_deprecated=outcome.tools_deprecated,
        insights=tuple(outcome.insights),
    )


def export_improvement_report(
    *,
    root: str | Path,
    report: ImprovementRunReport,
    path: str = "improvement_report.json",
) -> ImprovementReportBundle:
    """Write a persistable improvement report under ``root``."""

    payload = report.to_dict()
    _write_json(Path(root) / path, payload)
    return ImprovementReportBundle(report=payload)
