"""Tests for MetaSpecifier's pure-function markdown renderer."""

from __future__ import annotations

from cemaf.meta.goals import (
    CapabilityDelta,
    ProposalDoc,
    Requirement,
    Scenario,
    SpecGoal,
)
from cemaf.meta.specifier import render_proposal, template_proposal


def _sample_doc() -> ProposalDoc:
    return ProposalDoc(
        change_id="add-thing",
        title="Add Thing",
        why="Because we need it.",
        what_changes=("Introduce Thing", "Wire it up"),
        impact=("affected: thing-capability",),
        tasks=("Implement", "Test"),
        deltas=(
            CapabilityDelta(
                capability="thing",
                added_requirements=(
                    Requirement(
                        name="Thing works",
                        statement="The system SHALL do the thing.",
                        scenarios=(
                            Scenario(
                                name="happy",
                                given=("setup is ready",),
                                when=("the user triggers it",),
                                then=("the thing happens",),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def test_renders_expected_file_map() -> None:
    files = render_proposal(doc=_sample_doc())
    assert set(files.keys()) == {
        "proposal.md",
        "tasks.md",
        "specs/thing/spec.md",
    }


def test_proposal_has_why_section() -> None:
    files = render_proposal(doc=_sample_doc())
    assert files["proposal.md"].startswith("# Add Thing")
    assert "## Why" in files["proposal.md"]
    assert "Because we need it." in files["proposal.md"]


def test_spec_has_added_requirements_structure() -> None:
    files = render_proposal(doc=_sample_doc())
    spec = files["specs/thing/spec.md"]
    assert spec.startswith("# thing capability")
    assert "## ADDED Requirements" in spec
    assert "### Requirement: Thing works" in spec
    assert "#### Scenario: happy" in spec
    assert "- **GIVEN** setup is ready" in spec
    assert "- **WHEN** the user triggers it" in spec
    assert "- **THEN** the thing happens" in spec


def test_render_is_deterministic() -> None:
    doc = _sample_doc()
    a = render_proposal(doc=doc)
    b = render_proposal(doc=doc)
    assert a == b


def test_tasks_fallback_when_empty() -> None:
    doc = ProposalDoc(
        change_id="empty",
        title="Empty",
        why="x",
        tasks=(),
    )
    files = render_proposal(doc=doc)
    assert "- [ ] Define concrete tasks" in files["tasks.md"]


def test_template_proposal_matches_goal_structure() -> None:
    goal = SpecGoal(
        feature_description="add cache invalidation",
        change_id="add-cache-invalidation",
        capabilities=("cache", "http"),
    )
    doc = template_proposal(goal=goal)
    assert doc.change_id == "add-cache-invalidation"
    assert {d.capability for d in doc.deltas} == {"cache", "http"}
    for delta in doc.deltas:
        assert len(delta.added_requirements) >= 1
        for req in delta.added_requirements:
            assert len(req.scenarios) >= 1
            for scenario in req.scenarios:
                assert scenario.given and scenario.when and scenario.then


def test_template_proposal_renders_to_valid_openspec_shape() -> None:
    goal = SpecGoal(
        feature_description="add cache invalidation",
        change_id="add-cache-invalidation",
        capabilities=("cache",),
    )
    files = render_proposal(doc=template_proposal(goal=goal))
    spec = files["specs/cache/spec.md"]
    assert "## ADDED Requirements" in spec
    assert "### Requirement:" in spec
    assert "#### Scenario:" in spec
