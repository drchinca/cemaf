"""End-to-end triad loop — harvest from run A, retrieve in run B.

This is the *headline* behavior of the blueprint triad. Without this
test, PRs 97 / 98 / 99 are three tested limbs with no tested joint.

Flow under test:

    Run A (high-quality):
      TASK_STARTED  → correlator captures goal
      TASK_COMPLETED → correlator captures output
      EVAL_COMPLETED → harvester derives RECIPE,
                       appends to writable source,
                       registers in library

    Run B (same-goal similarity):
      ContextNodeExecutor._compile_context runs
      → selector hook consults library
      → resolved blueprint's prompt lands in artifacts
        under key "blueprint:selected" at index 0
"""

from __future__ import annotations

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.blueprint.harvest import BlueprintHarvesterEngine
from cemaf.blueprint.harvest_defaults import (
    InMemoryRunCorrelator,
    RecipeBlueprintDistiller,
    ScoreThresholdHarvestPolicy,
)
from cemaf.blueprint.library import BlueprintEntryKind, BlueprintLibrary
from cemaf.blueprint.sources import InMemoryWritableBlueprintSource
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.meta.blueprint_selector import LibraryBlueprintSelectorHook
from cemaf.orchestration.context_node_executor import ContextNodeExecutor


@pytest.mark.asyncio
async def test_harvest_from_run_a_retrieved_in_run_b() -> None:
    """Full triad closes the loop: a high-quality run grows the library,
    a subsequent similar-goal run retrieves the harvested RECIPE."""
    bus = InMemoryEventBus()
    source = InMemoryWritableBlueprintSource()
    library = BlueprintLibrary()

    # Harvester subscribed — autonomous write path.
    engine = BlueprintHarvesterEngine(
        writable_source=source,
        library=library,
        policy=ScoreThresholdHarvestPolicy(threshold=0.8),
        correlator=InMemoryRunCorrelator(),
        distiller=RecipeBlueprintDistiller(),
    )
    engine.subscribe(event_bus=bus)

    # ---- Run A: a high-quality run that should be harvested ----
    goal_text = "Write a product launch announcement"
    await bus.publish(
        Event.create(
            type=EventType.TASK_STARTED,
            payload={
                "run_id": "run-A",
                "node_id": "Writer",
                "goal_text": goal_text,
                "inputs": {"objective": goal_text},
            },
            correlation_id="run-A",
        ),
    )
    await bus.publish(
        Event.create(
            type=EventType.TASK_COMPLETED,
            payload={
                "run_id": "run-A",
                "node_id": "Writer",
                "output": "# Launch\nWe shipped it.",
            },
            correlation_id="run-A",
        ),
    )
    await bus.publish(
        Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={
                "run_id": "run-A",
                "node_id": "Writer",
                "overall_score": 0.92,
                "overall_passed": True,
            },
            correlation_id="run-A",
        ),
    )

    # Invariant 1: library grew by exactly one harvested RECIPE.
    harvested = [e for e in library if e.id.startswith("harvest/")]
    assert len(harvested) == 1
    harvested_entry = harvested[0]
    assert harvested_entry.kind is BlueprintEntryKind.RECIPE

    # ---- Run B: a different run with a *matching* goal should retrieve it ----
    hook = LibraryBlueprintSelectorHook(library=library)
    executor = ContextNodeExecutor(
        agent_registry=AgentRegistry(),
        context_compiler=PriorityContextCompiler(
            token_estimator=SimpleTokenEstimator(chars_per_token=4.0),
        ),
        token_budget=TokenBudget(max_tokens=4000, reserved_for_output=500),
        blueprint_selector=hook,
    )

    compiled = await executor._compile_context(
        agent_name="Writer",
        inputs={"objective": goal_text},
        memories={},
    )

    # Invariant 2: the selector injected the harvested RECIPE's prompt.
    assert compiled is not None
    source_keys = [s.key for s in compiled.sources]
    assert "blueprint:selected" in source_keys
    # Invariant 3: blueprint arrives at index 0 — highest priority.
    assert source_keys[0] == "blueprint:selected"

    # Invariant 4: the injected prompt is the *harvested* entry's prompt,
    # not some other one that happened to be in the library.
    blueprint_artifact = next(s for s in compiled.sources if s.key == "blueprint:selected")
    assert goal_text in blueprint_artifact.content

    engine.unsubscribe()


@pytest.mark.asyncio
async def test_low_quality_run_does_not_grow_library() -> None:
    """Negative control — a sub-threshold run must not produce an entry."""
    bus = InMemoryEventBus()
    source = InMemoryWritableBlueprintSource()
    library = BlueprintLibrary()

    engine = BlueprintHarvesterEngine(
        writable_source=source,
        library=library,
        policy=ScoreThresholdHarvestPolicy(threshold=0.8),
        correlator=InMemoryRunCorrelator(),
        distiller=RecipeBlueprintDistiller(),
    )
    engine.subscribe(event_bus=bus)

    for event_type, payload in [
        (EventType.TASK_STARTED, {"goal_text": "low-value goal"}),
        (EventType.TASK_COMPLETED, {"output": "weak"}),
        (EventType.EVAL_COMPLETED, {"overall_score": 0.4, "overall_passed": False}),
    ]:
        await bus.publish(
            Event.create(
                type=event_type,
                payload={"run_id": "run-lo", "node_id": "Writer", **payload},
                correlation_id="run-lo",
            ),
        )

    assert len(library) == 0
    engine.unsubscribe()
