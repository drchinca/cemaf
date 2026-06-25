"""SPEC-13 integration — scoped distillers + real library + promotion end-to-end.

Two projects harvest the same goal through project-scoped distillers; both entries coexist
in one library (no clobber), and evaluate_promotion over the library marks the shared goal
for promotion to GLOBAL.
"""

import pytest

from cemaf.blueprint.core import BlueprintScope
from cemaf.blueprint.harvest import HarvestContext
from cemaf.blueprint.harvest_defaults import (
    ProjectScopedRecipeDistiller,
    evaluate_promotion,
)
from cemaf.blueprint.library import BlueprintLibrary
from cemaf.events.protocols import Event, EventType


def _ctx(goal: str) -> HarvestContext:
    return HarvestContext(run_id="r", node_id="n", goal_text=goal, output_text="result")


def _event(score: float) -> Event:
    return Event.create(type=EventType.EVAL_COMPLETED, payload={"overall_score": score})


@pytest.mark.asyncio
async def test_two_projects_coexist_then_promote() -> None:
    library = BlueprintLibrary()
    goal = "summarize the quarterly report"

    alpha = ProjectScopedRecipeDistiller(project_id="alpha")
    beta = ProjectScopedRecipeDistiller(project_id="beta")

    entry_a = await alpha.distill(event=_event(0.88), context=_ctx(goal))
    entry_b = await beta.distill(event=_event(0.82), context=_ctx(goal))
    assert entry_a is not None and entry_b is not None

    library.register(entry=entry_a)
    library.register(entry=entry_b)

    # Both coexist — no cross-project clobber.
    assert len(library.entries()) == 2
    assert {e.project_id for e in library.entries()} == {"alpha", "beta"}

    # Promotion over the real library marks the shared goal.
    decisions = evaluate_promotion(library.entries())
    promoted = [d for d in decisions if d.promote]
    assert len(promoted) == 1
    assert promoted[0].project_ids == ("alpha", "beta")
    assert promoted[0].mean_confidence == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_single_project_in_library_does_not_promote() -> None:
    library = BlueprintLibrary()
    alpha = ProjectScopedRecipeDistiller(project_id="alpha")
    entry = await alpha.distill(event=_event(0.95), context=_ctx("a lonely goal"))
    assert entry is not None
    library.register(entry=entry)

    decisions = evaluate_promotion(library.entries())
    assert all(not d.promote for d in decisions)
    assert all(e.scope is BlueprintScope.PROJECT for e in library.entries())
