"""Default entity extractor — deterministic, dependency-free.

PullInterceptor's pinned default. A future LLM-based extractor can implement
the same `EntityExtractor` protocol without changing call sites; bump
`version` when swapping algorithms so any pinned fixture cassettes invalidate.
"""

from __future__ import annotations

import re
from typing import ClassVar

from cemaf.datasources.models import EntityRef

# Requires >=2 capitalized humps (true CamelCase/PascalCase, e.g. "OrderPipeline")
# so an ordinary sentence-starting capitalized word ("Look up...") never false-positives.
_CAMEL_CASE_RE = re.compile(r"\b(?:[A-Z][a-z0-9]*){2,}\b")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class DefaultEntityExtractor:
    """Gazetteer exact match (case-insensitive) + CamelCase/PascalCase regex fallback."""

    version: ClassVar[str] = "1.0.0"

    def __init__(self, *, gazetteer: frozenset[str] = frozenset()) -> None:
        self._gazetteer = gazetteer
        self._gazetteer_lower = {entry.lower(): entry for entry in gazetteer}

    def extract(self, *, text: str) -> tuple[EntityRef, ...]:
        if not text:
            return ()

        seen: set[str] = set()
        refs: list[EntityRef] = []

        lowered = text.lower()
        for entry_lower, entry in self._gazetteer_lower.items():
            if entry_lower in lowered and entry not in seen:
                seen.add(entry)
                refs.append(EntityRef(id=_slug(entry), label=entry))

        for match in _CAMEL_CASE_RE.finditer(text):
            label = match.group(0)
            if label not in seen:
                seen.add(label)
                refs.append(EntityRef(id=_slug(label), label=label))

        return tuple(refs)
