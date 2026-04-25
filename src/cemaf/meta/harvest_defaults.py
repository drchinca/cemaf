"""Default implementations of the three harvest decision protocols.

Each class here is one concrete way to answer one question that
`BlueprintHarvesterEngine` asks:

- `ScoreThresholdHarvestPolicy`: "Is this run good enough to harvest?"
  → True when `event.payload["overall_score"] >= threshold`
  and `overall_passed` is truthy.

- `InMemoryRunCorrelator`: "What do we know about this run?"
  → Watches `TASK_STARTED` (goal) + `TASK_COMPLETED` (output),
  indexes by `(run_id, node_id)`, caps growth with a per-entry TTL.

- `RecipeBlueprintDistiller`: "What blueprint does this run yield?"
  → Builds a RECIPE-kind `BlueprintEntry` with a content-addressed id
  (`harvest/{sha256(goal_text)[:12]}`) so repeated harvests upsert
  cleanly instead of piling up duplicates.

Every class here is a plain concrete implementation — use them directly,
subclass them, or ignore them entirely. The engine in `blueprint/harvest.py`
doesn't care which you pick.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from cemaf.blueprint.harvest import HarvestContext
from cemaf.blueprint.library import BlueprintEntry
from cemaf.events.protocols import Event

logger = logging.getLogger(__name__)


# =============================================================================
# Policy — threshold over an eval score
# =============================================================================


class ScoreThresholdHarvestPolicy:
    """Harvest when `overall_score >= threshold` and `overall_passed` is truthy.

    Both fields live on the `EVAL_COMPLETED` payload (see
    `evals/online.py`). A minimum ceiling (`min_threshold`) guards against
    misconfiguration — a threshold of 0.0 would harvest every run.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.8,
        require_passed: bool = True,
        min_threshold: float = 0.5,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0.0, 1.0]; got {threshold}")
        if threshold < min_threshold:
            raise ValueError(
                f"threshold ({threshold}) is below min_threshold ({min_threshold}) — "
                "would harvest too aggressively."
            )
        self._threshold = threshold
        self._require_passed = require_passed

    def should_harvest(self, *, event: Event) -> bool:
        score = event.payload.get("overall_score")
        if not isinstance(score, int | float):
            return False
        if float(score) < self._threshold:
            return False
        return not (self._require_passed and not bool(event.payload.get("overall_passed", False)))


# =============================================================================
# Correlator — in-memory, TTL-capped
# =============================================================================


class _CorrelatorEntry:
    __slots__ = ("goal_text", "output_text", "extras", "touched_at")

    def __init__(self) -> None:
        self.goal_text: str = ""
        self.output_text: str = ""
        self.extras: dict[str, Any] = {}
        self.touched_at: float = time.monotonic()


class InMemoryRunCorrelator:
    """Correlates `TASK_STARTED` + `TASK_COMPLETED` by (run_id, node_id).

    Entries age out after `ttl_seconds` of inactivity; also capped at
    `max_entries` (LRU eviction on insert) so a runaway producer can't
    exhaust memory. Thread-safe only in the cooperative-asyncio sense:
    each observe/lookup is short and synchronous.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        max_entries: int = 10_000,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        # Ordered dict behavior: reinsert on touch for LRU.
        self._entries: dict[tuple[str, str], _CorrelatorEntry] = {}

    async def observe(self, *, event: Event) -> None:
        payload = event.payload
        run_id = _as_str(payload.get("run_id")) or _as_str(event.correlation_id)
        node_id = _as_str(payload.get("node_id"))
        if not run_id or not node_id:
            return

        self._evict_stale()
        key = (run_id, node_id)
        entry = self._entries.get(key)
        if entry is None:
            entry = _CorrelatorEntry()
            self._entries[key] = entry

        goal_text = payload.get("goal_text")
        if isinstance(goal_text, str) and goal_text:
            entry.goal_text = goal_text
        output = payload.get("output")
        if output is not None:
            entry.output_text = _coerce_text(output)
        inputs = payload.get("inputs")
        if isinstance(inputs, dict) and not entry.goal_text:
            entry.goal_text = _derive_goal_text(inputs=inputs)
        entry.touched_at = time.monotonic()

        # Enforce hard cap (cheap LRU: drop oldest by touched_at).
        if len(self._entries) > self._max_entries:
            oldest_key = min(self._entries, key=lambda k: self._entries[k].touched_at)
            self._entries.pop(oldest_key, None)

    async def lookup(self, *, run_id: str, node_id: str) -> HarvestContext | None:
        """Return context only when BOTH goal and output are captured.

        Returning partial context (goal only, no output) would let the
        engine harvest half-populated blueprints when `EVAL_COMPLETED`
        races ahead of `TASK_COMPLETED`. The stricter contract pushes
        the race handling up to the engine's retry loop.
        """
        self._evict_stale()
        entry = self._entries.get((run_id, node_id))
        if entry is None:
            return None
        if not entry.goal_text or not entry.output_text:
            return None
        return HarvestContext(
            run_id=run_id,
            node_id=node_id,
            goal_text=entry.goal_text,
            output_text=entry.output_text,
            extras=dict(entry.extras),
        )

    def _evict_stale(self) -> None:
        if self._ttl <= 0:
            return
        cutoff = time.monotonic() - self._ttl
        stale = [key for key, e in self._entries.items() if e.touched_at < cutoff]
        for key in stale:
            self._entries.pop(key, None)


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict | list | tuple):
        try:
            import json as _json

            return _json.dumps(value, default=str)
        except Exception:
            return str(value)
    return str(value)


def _derive_goal_text(*, inputs: dict[str, Any]) -> str:
    """Best-effort goal extraction from TASK_STARTED inputs."""
    for key in ("objective", "goal", "description", "task", "query", "feature_description"):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value
    # Fallback — serialize the inputs so the distiller has something to work with.
    return _coerce_text(inputs)


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


# =============================================================================
# Distiller — content-addressed RECIPE entries
# =============================================================================


class RecipeBlueprintDistiller:
    """Build a RECIPE `BlueprintEntry` from a harvest context.

    Entry id is content-addressed on the goal text: `harvest/{sha256(goal)[:12]}`.
    This gives idempotent upsert — running the same goal again won't
    multiply entries; it will refresh the existing one.

    Title defaults to a truncated goal; tag set defaults to ("harvested",).
    Override by subclassing if you want fancier derivation (e.g. NLP
    summarization of the output, style inference, auto-tagging).
    """

    def __init__(
        self,
        *,
        tags: tuple[str, ...] = ("harvested",),
        title_max_chars: int = 80,
        source_name: str = "harvest",
    ) -> None:
        self._tags = tags
        self._title_max_chars = title_max_chars
        self._source_name = source_name

    async def distill(
        self,
        *,
        event: Event,
        context: HarvestContext,
    ) -> BlueprintEntry | None:
        goal_text = context.goal_text.strip()
        if not goal_text:
            return None

        digest = hashlib.sha256(goal_text.encode("utf-8")).hexdigest()[:12]
        entry_id = f"harvest/{digest}"
        title = _truncate(text=goal_text, limit=self._title_max_chars)

        score = event.payload.get("overall_score")
        score_str = f"{float(score):.2f}" if isinstance(score, int | float) else "?"

        recipe: dict[str, Any] = {
            "name": title,
            "goal": goal_text,
            "description": (
                f"Harvested from a successful run (score={score_str}, "
                f"run_id={context.run_id!r}, node_id={context.node_id!r})."
            ),
        }

        # Attach the output as a style example when it's short-ish prose;
        # distillers that want richer derivation should subclass.
        if context.output_text and len(context.output_text) <= 2000:
            recipe["style"] = {"examples": [context.output_text]}

        return BlueprintEntry.recipe_entry(
            id=entry_id,
            title=title,
            recipe=recipe,
            tags=self._tags,
            source=self._source_name,
        )


def _truncate(*, text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


__all__ = [
    "InMemoryRunCorrelator",
    "RecipeBlueprintDistiller",
    "ScoreThresholdHarvestPolicy",
]
