"""Helpers for exporting generic citation-tracker artifacts to disk."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cemaf.core.utils import safe_json


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_json(payload), indent=2), encoding="utf-8")


@dataclass(frozen=True)
class CitationArtifactsBundle:
    """Serialized citation artifacts written from a citation tracker."""

    payload: dict[str, Any]


def export_citation_artifacts(*, root: str | Path, tracker: Any) -> CitationArtifactsBundle:
    """Write ``citations.json`` for any tracker exposing the CEMAF citation surface."""

    run_dir = Path(root)
    run_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "report": tracker.get_citation_report(),
        "citations": [citation.to_dict() for citation in tracker.get_all_citations()],
        "cited_facts": [fact.to_dict() for fact in tracker.get_cited_facts()],
        "uncited_facts": list(tracker.get_uncited_facts()),
    }
    _write_json(run_dir / "citations.json", payload)
    return CitationArtifactsBundle(payload=payload)
