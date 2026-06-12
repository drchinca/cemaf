"""Protocol-first harvesting — the engine that grows the blueprint library autonomously.

This module defines the **agnostic substrate** for blueprint harvesting:
the engine knows *nothing* about quality thresholds, correlation rules,
or how to derive a blueprint from a run. Every judgment is a protocol
that the caller provides — BYO policy, BYO correlator, BYO distiller.

Composition:

    policy.should_harvest(event) ────────────────── True/False
                                │
                                ▼ (True)
    correlator.lookup(run_id, node_id) ──────────── HarvestContext
                                │
                                ▼
    distiller.distill(event, context) ───────────── BlueprintEntry | None
                                │
                                ▼ (non-None)
    writable_source.append(entry)
    library.register_async(entry, overwrite=True)

The engine itself (`BlueprintHarvesterEngine`) subscribes to configurable
trigger + observe events and drives this four-step pipeline — nothing
else. It has no hardcoded event types, no score thresholds, no derivation
rules.

Default implementations for the three decision protocols live in
`cemaf.blueprint.harvest_defaults` (score-threshold policy, in-memory
TTL-capped correlator, recipe distiller) — they're opt-in, not the only
way.

This is the "flesh" of the triad: the library doesn't just read itself,
it grows itself, and the **shape of the growth is pluggable**.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cemaf.blueprint.library import (
    BlueprintEntry,
    BlueprintIdCollision,
    BlueprintLibrary,
    WritableBlueprintSource,
)
from cemaf.core.types import JSON
from cemaf.events.protocols import Event, EventBus, EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HarvestContext:
    """Correlated run context handed to the distiller.

    Everything the engine knows about a run at harvest time: the run/node
    identifiers, the goal text the agent was given, the output text it
    produced, plus arbitrary extras a correlator may attach. All fields
    are plain JSON-safe so distillers can serialize freely.
    """

    run_id: str
    node_id: str
    goal_text: str = ""
    output_text: str = ""
    extras: JSON = field(default_factory=dict)


@runtime_checkable
class HarvestPolicy(Protocol):
    """Decides whether a given trigger event warrants a harvest attempt."""

    def should_harvest(self, *, event: Event) -> bool:
        """Return True to proceed to correlation + distillation; False to skip."""
        ...


@runtime_checkable
class RunCorrelator(Protocol):
    """Accumulates cross-event context keyed by (run_id, node_id).

    A correlator observes whichever events carry the data the distiller
    needs (typically TASK_STARTED for goal, TASK_COMPLETED for output)
    and exposes a lookup the engine calls at trigger time. Implementations
    decide their own storage + TTL policy.
    """

    async def observe(self, *, event: Event) -> None:
        """Record data from an event. Safe to call with any event type."""
        ...

    async def lookup(self, *, run_id: str, node_id: str) -> HarvestContext | None:
        """Return the correlated context for this run/node, or None if unknown."""
        ...


@runtime_checkable
class BlueprintDistiller(Protocol):
    """Produces a `BlueprintEntry` from a trigger event + correlated context.

    Returning `None` aborts the harvest silently (the engine logs at debug
    level). Raising propagates — callers can route errors via the engine's
    optional on_error callback.
    """

    async def distill(
        self,
        *,
        event: Event,
        context: HarvestContext,
    ) -> BlueprintEntry | None:
        """Build and return a `BlueprintEntry`, or None to skip."""
        ...


@dataclass(frozen=True)
class HarvestOutcome:
    """What the engine did on a single trigger event. For telemetry + tests."""

    accepted: bool
    entry_id: str | None = None
    reason: str = ""


class BlueprintHarvesterEngine:
    """Substrate-agnostic harvesting engine — composes four pluggable decisions.

    The engine is the only piece that knows about EventBus mechanics. It
    does not know what "high quality" means, how to extract a goal from
    an event, or how to turn a run into a blueprint — those are the
    caller's responsibility via the three protocols above.

    Lifecycle:
      1. `__init__` with deps; does not touch any bus.
      2. `subscribe(event_bus=...)` wires both observe and trigger events.
      3. Events flow: observe events → correlator.observe(); trigger events
         → policy.should_harvest → correlator.lookup → distiller.distill →
         writable_source.append + library.register_async(overwrite=True).
      4. `unsubscribe()` releases every handler. Idempotent.
    """

    def __init__(
        self,
        *,
        writable_source: WritableBlueprintSource,
        policy: HarvestPolicy,
        correlator: RunCorrelator,
        distiller: BlueprintDistiller,
        library: BlueprintLibrary | None = None,
        trigger_events: tuple[EventType, ...] = (EventType.EVAL_COMPLETED,),
        observe_events: tuple[EventType, ...] = (
            EventType.TASK_STARTED,
            EventType.TASK_COMPLETED,
        ),
        on_outcome: Callable[[HarvestOutcome], None] | None = None,
        correlation_retry_attempts: int = 3,
        correlation_retry_delay_s: float = 0.05,
    ) -> None:
        self._source = writable_source
        self._policy = policy
        self._correlator = correlator
        self._distiller = distiller
        self._library = library
        self._trigger_events = trigger_events
        self._observe_events = observe_events
        self._on_outcome = on_outcome
        # Correlation retry guards the race where a TRIGGER event (EVAL_COMPLETED)
        # reaches this handler before the final OBSERVE event (TASK_COMPLETED)
        # under bus subscription-order or concurrent-dispatch scheduling.
        # We re-poll the correlator up to N times with a short delay — bounded,
        # so a genuinely orphaned eval still fails fast.
        if correlation_retry_attempts < 0:
            raise ValueError(f"correlation_retry_attempts must be >= 0; got {correlation_retry_attempts}")
        if correlation_retry_delay_s < 0:
            raise ValueError(f"correlation_retry_delay_s must be >= 0; got {correlation_retry_delay_s}")
        self._retry_attempts = correlation_retry_attempts
        self._retry_delay = correlation_retry_delay_s
        self._unsubscribers: list[Callable[[], None]] = []

    def subscribe(self, *, event_bus: EventBus) -> None:
        """Wire observer + trigger handlers onto the bus. Idempotent relative to `unsubscribe`."""
        for event_type in self._observe_events:
            unsub = event_bus.subscribe(event_type, self._observe_handler)
            self._unsubscribers.append(unsub)
        for event_type in self._trigger_events:
            unsub = event_bus.subscribe(event_type, self._trigger_handler)
            self._unsubscribers.append(unsub)

    def unsubscribe(self) -> None:
        """Tear down every subscription created by `subscribe`. Safe to call twice."""
        while self._unsubscribers:
            unsub = self._unsubscribers.pop()
            try:
                unsub()
            except Exception:
                # Best-effort — unsubscribe must not raise during shutdown.
                logger.debug("Unsubscribe callback raised", exc_info=True)

    async def _observe_handler(self, event: Event) -> None:
        """Forward every observe event into the correlator. Errors are logged but not raised."""
        try:
            await self._correlator.observe(event=event)
        except Exception:
            logger.warning(
                "Correlator.observe raised for event %s — dropping",
                event.type,
                exc_info=True,
            )

    async def _trigger_handler(self, event: Event) -> None:
        """Run policy → correlator → distiller → persist for a trigger event."""
        outcome = await self._maybe_harvest(event=event)
        if self._on_outcome is not None:
            try:
                self._on_outcome(outcome)
            except Exception:
                logger.debug("on_outcome callback raised", exc_info=True)

    async def _lookup_with_retry(
        self,
        *,
        run_id: str,
        node_id: str,
    ) -> HarvestContext | None:
        """Poll the correlator up to N times with a short delay between attempts.

        Guards the race where EVAL_COMPLETED reaches the engine before the
        correlator has finished observing the originating run's
        TASK_COMPLETED. The first attempt happens immediately — retries
        only kick in when the correlator genuinely doesn't have the data
        yet. Bounded by `correlation_retry_attempts` so orphaned evals
        fail fast.
        """
        for attempt in range(self._retry_attempts + 1):
            context = await self._correlator.lookup(run_id=run_id, node_id=node_id)
            if context is not None:
                return context
            if attempt < self._retry_attempts:
                await asyncio.sleep(self._retry_delay)
        return None

    async def _maybe_harvest(self, *, event: Event) -> HarvestOutcome:
        if not self._policy.should_harvest(event=event):
            return HarvestOutcome(accepted=False, reason="policy_rejected")

        run_id, node_id = _extract_run_and_node(event=event)
        if not run_id or not node_id:
            return HarvestOutcome(accepted=False, reason="missing_run_or_node_id")

        context = await self._lookup_with_retry(run_id=run_id, node_id=node_id)
        if context is None:
            logger.warning(
                "Harvest dropped — no correlation after %d attempt(s) for run=%s node=%s. "
                "Likely cause: EVAL_COMPLETED arrived before TASK_COMPLETED (subscription-order "
                "race) or the correlator was never fed goal/output for this run.",
                self._retry_attempts + 1,
                run_id,
                node_id,
            )
            return HarvestOutcome(accepted=False, reason="no_correlation")

        try:
            entry = await self._distiller.distill(event=event, context=context)
        except Exception as exc:
            logger.warning(
                "Distiller raised on %s/%s: %s",
                run_id,
                node_id,
                exc,
                exc_info=True,
            )
            return HarvestOutcome(accepted=False, reason=f"distiller_error:{type(exc).__name__}")

        if entry is None:
            return HarvestOutcome(accepted=False, reason="distiller_skipped")

        try:
            await self._source.append(entry=entry)
        except Exception as exc:
            logger.warning(
                "WritableBlueprintSource.append raised for %r: %s",
                entry.id,
                exc,
                exc_info=True,
            )
            return HarvestOutcome(
                accepted=False,
                entry_id=entry.id,
                reason=f"source_append_error:{type(exc).__name__}",
            )

        if self._library is not None:
            try:
                await self._library.register_async(entry=entry, overwrite=True)
            except BlueprintIdCollision:
                # Cannot happen with overwrite=True, but keep the arm for future-proofing.
                logger.debug("Library rejected %r despite overwrite=True", entry.id)

        return HarvestOutcome(accepted=True, entry_id=entry.id, reason="appended")


def _extract_run_and_node(*, event: Event) -> tuple[str, str]:
    """Best-effort extraction of (run_id, node_id) from an event payload.

    Events vary in payload shape — `correlation_id` is the canonical
    run-scoped identifier, but individual event types may also stash
    `run_id`/`node_id` inline. This helper tries both and tolerates
    mixed-type payload values (ints, strs, None).
    """
    payload = event.payload
    run_id = _as_str(payload.get("run_id")) or _as_str(event.correlation_id)
    node_id = _as_str(payload.get("node_id"))
    return run_id, node_id


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


__all__ = [
    "BlueprintDistiller",
    "BlueprintHarvesterEngine",
    "HarvestContext",
    "HarvestOutcome",
    "HarvestPolicy",
    "RunCorrelator",
]
