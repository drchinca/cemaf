"""SPEC-11 integration — clearance gate through the REAL compiler + selection under budget,
and security_level survival across the REAL ContextPatch/PatchLog provenance round-trip.

The unit tests assert "key appears in security_excluded". This proves the behavioral contract:
gating runs through the real PriorityContextCompiler + GreedySelectionAlgorithm + TokenBudget,
so excluding an over-clearance source actually changes WHICH sources fit; and a patch's
security_level survives serialize→from_dict→replay (the checkpoint persistence boundary).
"""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchLog, PatchSource, SecurityLevel


def _compiler() -> PriorityContextCompiler:
    # 4 chars/token estimator → predictable token math for budget pressure.
    return PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=4.0))


class TestClearanceGateUnderRealBudget:
    @pytest.mark.asyncio
    async def test_gate_frees_budget_for_lower_clearance_content(self) -> None:
        """The real behavioral payoff: gating a high-priority CONFIDENTIAL source under tight
        budget lets a lower-priority INTERNAL source take its place — selection changes, not
        just the excluded list."""
        compiler = _compiler()
        # ~25 tokens each (100 chars / 4). Budget fits only ONE.
        artifacts = (
            ("secret", "x" * 100),  # CONFIDENTIAL, highest priority — would win if ungated
            ("notes", "y" * 100),  # INTERNAL, lower priority
        )
        priorities = {"secret": 100, "notes": 1}
        budget = TokenBudget(max_tokens=30, reserved_for_output=0)  # room for ~one source

        # Ungated: the high-priority confidential source wins the single slot.
        ungated = await compiler.compile(
            artifacts=artifacts, memories=(), budget=budget, priorities=priorities
        )
        assert [s.key for s in ungated.sources] == ["secret"]

        # Gated at INTERNAL clearance: 'secret' is dropped BEFORE selection, so 'notes' — which
        # would otherwise have lost on priority — now fits the freed slot.
        gated = await compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
            priorities=priorities,
            source_levels={"secret": SecurityLevel.CONFIDENTIAL, "notes": SecurityLevel.INTERNAL},
            clearance=SecurityLevel.INTERNAL,
        )
        assert [s.key for s in gated.sources] == ["notes"]
        assert "secret" in gated.metadata.get("security_excluded", [])
        assert gated.within_budget()

    @pytest.mark.asyncio
    async def test_confidential_clearance_keeps_everything_selectable(self) -> None:
        """With full clearance and ample budget, nothing is gated — gate doesn't over-exclude."""
        compiler = _compiler()
        artifacts = (("a", "aa"), ("b", "bb"), ("c", "cc"))
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
        result = await compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
            source_levels={
                "a": SecurityLevel.PUBLIC,
                "b": SecurityLevel.INTERNAL,
                "c": SecurityLevel.CONFIDENTIAL,
            },
            clearance=SecurityLevel.CONFIDENTIAL,
        )
        assert {s.key for s in result.sources} == {"a", "b", "c"}
        assert result.metadata.get("security_excluded", []) == []

    @pytest.mark.asyncio
    async def test_ungated_compile_is_byte_identical_to_pre_spec11(self) -> None:
        """Non-interference: clearance=None yields the exact same compiled content_hash as
        omitting the security kwargs entirely (the pre-SPEC-11 call shape)."""
        compiler = _compiler()
        artifacts = (("a", "alpha"), ("b", "beta"))
        memories = (("m", "memo"),)
        budget = TokenBudget(max_tokens=1000, reserved_for_output=0)

        legacy = await compiler.compile(artifacts=artifacts, memories=memories, budget=budget)
        with_kwargs = await compiler.compile(
            artifacts=artifacts,
            memories=memories,
            budget=budget,
            source_levels={"a": SecurityLevel.CONFIDENTIAL},
            clearance=None,
        )
        assert with_kwargs.content_hash == legacy.content_hash


class TestSecurityLevelProvenanceRoundTrip:
    def test_level_survives_patchlog_serialize_replay(self) -> None:
        """security_level survives the real persistence path: build patches with mixed levels,
        serialize each (to_dict) → from_dict → replay through PatchLog onto a Context."""
        log = PatchLog().extend(
            (
                ContextPatch.set(
                    "public.fact", "ok", source=PatchSource.TOOL, security_level=SecurityLevel.PUBLIC
                ),
                ContextPatch.set(
                    "secret.key", "shh", source=PatchSource.AGENT, security_level=SecurityLevel.CONFIDENTIAL
                ),
                ContextPatch.set("plain.note", "hi"),  # defaults INTERNAL
            )
        )

        # Round-trip every patch through the serialization boundary (what checkpoints persist).
        restored = PatchLog().extend(tuple(ContextPatch.from_dict(p.to_dict()) for p in log))
        levels = {p.path: p.security_level for p in restored}
        assert levels["public.fact"] is SecurityLevel.PUBLIC
        assert levels["secret.key"] is SecurityLevel.CONFIDENTIAL
        assert levels["plain.note"] is SecurityLevel.INTERNAL

        # And the restored log still applies cleanly to a real Context.
        final = restored.replay(Context())
        assert final.get("public.fact") == "ok"
        assert final.get("secret.key") == "shh"

    def test_filter_by_source_preserves_levels(self) -> None:
        """Provenance filtering (a real PatchLog operation) doesn't drop the classification."""
        log = PatchLog().extend(
            (
                ContextPatch.set("a", 1, source=PatchSource.AGENT, security_level=SecurityLevel.CONFIDENTIAL),
                ContextPatch.set("b", 2, source=PatchSource.TOOL, security_level=SecurityLevel.PUBLIC),
            )
        )
        agent_only = log.filter_by_source(PatchSource.AGENT)
        assert len(agent_only) == 1
        assert agent_only[0].security_level is SecurityLevel.CONFIDENTIAL
