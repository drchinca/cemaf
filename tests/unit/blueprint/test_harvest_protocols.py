"""Contract tests — the three harvest protocols are structurally typed and pluggable."""

from __future__ import annotations

import pytest

from cemaf.blueprint.harvest import (
    BlueprintDistiller,
    HarvestContext,
    HarvestPolicy,
    RunCorrelator,
)
from cemaf.meta.harvest_defaults import (
    InMemoryRunCorrelator,
    RecipeBlueprintDistiller,
    ScoreThresholdHarvestPolicy,
)


class TestPolicyContract:
    def test_threshold_policy_conforms(self) -> None:
        assert isinstance(ScoreThresholdHarvestPolicy(), HarvestPolicy)

    def test_custom_policy_conforms(self) -> None:
        class AlwaysTrue:
            def should_harvest(self, *, event) -> bool:  # type: ignore[no-untyped-def]
                return True

        assert isinstance(AlwaysTrue(), HarvestPolicy)

    def test_plain_object_rejected(self) -> None:
        class Impostor:
            pass

        assert not isinstance(Impostor(), HarvestPolicy)


class TestCorrelatorContract:
    def test_in_memory_correlator_conforms(self) -> None:
        assert isinstance(InMemoryRunCorrelator(), RunCorrelator)

    def test_custom_correlator_conforms(self) -> None:
        class MiniCorrelator:
            async def observe(self, *, event) -> None:  # type: ignore[no-untyped-def]
                return None

            async def lookup(self, *, run_id: str, node_id: str) -> HarvestContext | None:
                return None

        assert isinstance(MiniCorrelator(), RunCorrelator)


class TestDistillerContract:
    def test_recipe_distiller_conforms(self) -> None:
        assert isinstance(RecipeBlueprintDistiller(), BlueprintDistiller)

    def test_custom_distiller_conforms(self) -> None:
        class NullDistiller:
            async def distill(self, *, event, context):  # type: ignore[no-untyped-def]
                return None

        assert isinstance(NullDistiller(), BlueprintDistiller)


class TestHarvestContextShape:
    def test_frozen(self) -> None:
        ctx = HarvestContext(run_id="r", node_id="n", goal_text="g")
        with pytest.raises(Exception):
            ctx.goal_text = "mutated"  # type: ignore[misc]

    def test_defaults(self) -> None:
        ctx = HarvestContext(run_id="r", node_id="n")
        assert ctx.goal_text == ""
        assert ctx.output_text == ""
        assert ctx.extras == {}
