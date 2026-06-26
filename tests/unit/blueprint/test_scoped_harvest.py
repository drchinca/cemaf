"""SPEC-13 — scoped blueprint harvest: scoping fields, scoped distiller, promotion."""

import pytest

from cemaf.blueprint.core import Blueprint, BlueprintScope, SceneGoal
from cemaf.blueprint.harvest import HarvestContext
from cemaf.blueprint.harvest_defaults import (
    PROMOTE_MIN_CONFIDENCE,
    PROMOTE_MIN_PROJECTS,
    ProjectScopedRecipeDistiller,
    RecipeBlueprintDistiller,
    evaluate_promotion,
    goal_digest,
)
from cemaf.blueprint.library import BlueprintEntry
from cemaf.events.protocols import Event, EventType


def _blueprint() -> Blueprint:
    return Blueprint(id="bp1", name="n", scene_goal=SceneGoal(objective="do a thing"))


def _ctx(goal: str = "write a haiku") -> HarvestContext:
    return HarvestContext(run_id="r1", node_id="n1", goal_text=goal, output_text="out")


def _eval_event(score: float = 0.85) -> Event:
    return Event.create(type=EventType.EVAL_COMPLETED, payload={"overall_score": score})


def _entry(
    *,
    project_id: str,
    confidence: float,
    goal: str = "g",
    scope: BlueprintScope = BlueprintScope.PROJECT,
) -> BlueprintEntry:
    return BlueprintEntry.recipe_entry(
        id=f"harvest/{project_id}/{goal_digest(goal)}",
        title="t",
        recipe={"name": "t", "goal": goal},
        project_id=project_id,
        confidence=confidence,
        scope=scope,
    )


class TestScopingFields:
    def test_blueprint_defaults(self) -> None:
        """Inv 1 — defaults: PROJECT scope, 0.5 confidence, empty project_id."""
        bp = _blueprint()
        assert bp.scope is BlueprintScope.PROJECT
        assert bp.confidence == 0.5
        assert bp.project_id == ""

    def test_blueprint_round_trip_preserves_scope(self) -> None:
        bp = Blueprint(
            id="x",
            name="n",
            scene_goal=SceneGoal(objective="o"),
            project_id="alpha",
            confidence=0.9,
            scope=BlueprintScope.GLOBAL,
        )
        restored = Blueprint.from_dict(bp.to_dict())
        assert restored.project_id == "alpha"
        assert restored.confidence == 0.9
        assert restored.scope is BlueprintScope.GLOBAL

    def test_legacy_dict_without_scope_loads_defaults(self) -> None:
        """Backward compat — a pre-SPEC-13 serialized blueprint loads with defaults."""
        legacy = {"id": "x", "name": "n", "scene_goal": {"objective": "o"}}
        bp = Blueprint.from_dict(legacy)
        assert bp.scope is BlueprintScope.PROJECT
        assert bp.confidence == 0.5

    def test_entry_defaults(self) -> None:
        entry = BlueprintEntry.recipe_entry(id="e", title="t", recipe={"goal": "g"})
        assert entry.scope is BlueprintScope.PROJECT
        assert entry.confidence == 0.5
        assert entry.project_id == ""

    def test_entry_rejects_out_of_range_confidence(self) -> None:
        from cemaf.blueprint.library import BlueprintLibraryError

        with pytest.raises(BlueprintLibraryError):
            BlueprintEntry.recipe_entry(id="e", title="t", recipe={"g": 1}, confidence=1.5)
        with pytest.raises(BlueprintLibraryError):
            BlueprintEntry.recipe_entry(id="e", title="t", recipe={"g": 1}, confidence=-0.1)

    def test_blueprint_rejects_out_of_range_confidence(self) -> None:
        """Inv 2 — Blueprint's Pydantic Field bounds confidence to [0,1]."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Blueprint(id="x", name="n", scene_goal=SceneGoal(objective="o"), confidence=1.5)
        with pytest.raises(ValidationError):
            Blueprint(id="x", name="n", scene_goal=SceneGoal(objective="o"), confidence=-0.1)


class TestScopedDistiller:
    @pytest.mark.asyncio
    async def test_same_goal_different_projects_no_clobber(self) -> None:
        """Inv 3 — identical goal in two projects ⇒ distinct entry ids."""
        alpha = ProjectScopedRecipeDistiller(project_id="alpha")
        beta = ProjectScopedRecipeDistiller(project_id="beta")
        ea = await alpha.distill(event=_eval_event(), context=_ctx())
        eb = await beta.distill(event=_eval_event(), context=_ctx())
        assert ea is not None and eb is not None
        assert ea.id != eb.id
        assert ea.project_id == "alpha"
        assert eb.project_id == "beta"
        assert ea.scope is BlueprintScope.PROJECT

    @pytest.mark.asyncio
    async def test_empty_project_id_uses_legacy_id(self) -> None:
        """Inv 4 — empty project_id falls back to the pre-SPEC-13 unscoped id."""
        scoped_empty = ProjectScopedRecipeDistiller(project_id="")
        legacy = RecipeBlueprintDistiller()
        e1 = await scoped_empty.distill(event=_eval_event(), context=_ctx())
        e2 = await legacy.distill(event=_eval_event(), context=_ctx())
        assert e1 is not None and e2 is not None
        assert e1.id == e2.id == f"harvest/{goal_digest('write a haiku')}"

    @pytest.mark.asyncio
    async def test_confidence_derived_from_score(self) -> None:
        distiller = ProjectScopedRecipeDistiller(project_id="alpha")
        entry = await distiller.distill(event=_eval_event(score=0.92), context=_ctx())
        assert entry is not None
        assert entry.confidence == pytest.approx(0.92)


class TestPromotion:
    def test_promotes_across_two_projects_high_confidence(self) -> None:
        """Inv 5 — ≥2 distinct projects with mean confidence ≥0.8 ⇒ promote."""
        entries = (
            _entry(project_id="alpha", confidence=0.85),
            _entry(project_id="beta", confidence=0.85),
        )
        decisions = evaluate_promotion(entries)
        assert len(decisions) == 1
        assert decisions[0].promote is True
        assert decisions[0].project_ids == ("alpha", "beta")

    def test_single_project_never_promotes(self) -> None:
        """Inv 6 — three entries in ONE project do not meet the 2-project threshold."""
        entries = tuple(_entry(project_id="alpha", confidence=0.95) for _ in range(3))
        decisions = evaluate_promotion(entries)
        assert decisions[0].promote is False

    def test_low_mean_confidence_blocks_promotion(self) -> None:
        entries = (
            _entry(project_id="alpha", confidence=0.9),
            _entry(project_id="beta", confidence=0.6),
        )
        decisions = evaluate_promotion(entries)
        assert decisions[0].mean_confidence == pytest.approx(0.75)
        assert decisions[0].promote is False

    def test_already_global_entries_ignored(self) -> None:
        """Inv 7 — GLOBAL entries are not regrouped as PROJECT promotion candidates."""
        entries = (
            _entry(project_id="alpha", confidence=0.9, scope=BlueprintScope.GLOBAL),
            _entry(project_id="beta", confidence=0.9, scope=BlueprintScope.GLOBAL),
        )
        decisions = evaluate_promotion(entries)
        assert decisions == ()

    def test_thresholds_are_configurable(self) -> None:
        entries = (
            _entry(project_id="alpha", confidence=0.85),
            _entry(project_id="beta", confidence=0.85),
            _entry(project_id="gamma", confidence=0.85),
        )
        # require 3 projects — still promotes
        assert evaluate_promotion(entries, min_projects=3)[0].promote is True
        # require 4 projects — blocks
        assert evaluate_promotion(entries, min_projects=4)[0].promote is False

    def test_default_thresholds(self) -> None:
        assert PROMOTE_MIN_PROJECTS == 2
        assert PROMOTE_MIN_CONFIDENCE == 0.8

    def test_confidence_exactly_at_threshold_promotes(self) -> None:
        """Boundary — mean confidence == 0.8 promotes (>=, not >)."""
        entries = (
            _entry(project_id="alpha", confidence=0.8),
            _entry(project_id="beta", confidence=0.8),
        )
        assert evaluate_promotion(entries)[0].promote is True

    def test_two_distinct_projects_exactly_meets_min(self) -> None:
        """Boundary — exactly min_projects=2 distinct projects meets the threshold."""
        entries = (
            _entry(project_id="alpha", confidence=0.85),
            _entry(project_id="beta", confidence=0.85),
        )
        assert evaluate_promotion(entries, min_projects=2)[0].promote is True

    def test_duplicate_project_counts_once_and_uses_max(self) -> None:
        """Gap D — a project that harvested twice counts as ONE distinct project;
        its highest confidence is used, so duplicates can't skew the mean."""
        entries = (
            _entry(project_id="alpha", confidence=0.9),
            _entry(project_id="alpha", confidence=0.5),  # duplicate, lower
            _entry(project_id="beta", confidence=0.7),
        )
        decision = evaluate_promotion(entries)[0]
        assert decision.project_ids == ("alpha", "beta")  # 2 distinct, not 3
        # per-project: alpha=max(0.9,0.5)=0.9, beta=0.7 → mean 0.8
        assert decision.mean_confidence == pytest.approx(0.8)
        assert decision.promote is True

    def test_duplicate_project_alone_does_not_meet_distinct_threshold(self) -> None:
        """The promote decision keys on DISTINCT projects, not raw entry count: three high-
        confidence entries from ONE project (raw count 3 ≥ 2) must NOT promote. Co-locates the
        distinct-count guard with the duplicate-counting test (caught only by the single-project
        test otherwise — a raw-len() regression would slip past the test above)."""
        entries = (
            _entry(project_id="alpha", confidence=0.95),
            _entry(project_id="alpha", confidence=0.95),
            _entry(project_id="alpha", confidence=0.95),
        )
        decision = evaluate_promotion(entries)[0]
        assert decision.project_ids == ("alpha",)  # 1 distinct despite 3 entries
        assert decision.promote is False

    def test_mixed_global_and_project_same_digest_not_repromoted(self) -> None:
        """Inv 7 / Gap A — a digest with an existing GLOBAL entry is skipped entirely,
        even when fresh PROJECT copies exist (no double-promotion)."""
        entries = (
            _entry(project_id="alpha", confidence=0.9, scope=BlueprintScope.GLOBAL),
            _entry(project_id="beta", confidence=0.9),  # same goal "g" → same digest
            _entry(project_id="gamma", confidence=0.9),
        )
        decisions = evaluate_promotion(entries)
        assert decisions == ()  # digest already GLOBAL → not regrouped

    def test_empty_entries_returns_empty(self) -> None:
        assert evaluate_promotion(()) == ()
