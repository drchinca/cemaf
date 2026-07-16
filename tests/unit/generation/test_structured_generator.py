"""Unit tests for the pure helper functions in structured_generator.py."""

from cemaf.citation.models import Citation
from cemaf.generation.blueprint_request import PolicyKind, PolicySpec
from cemaf.generation.structured_generator import (
    _check_policy_violations,
    _filter_to_grounding_refs,
    _grounding_key,
)


def _citation(id_: str, source_id: str) -> Citation:
    return Citation(id=id_, source_id=source_id, source_type="document")


class TestGroundingKey:
    def test_key_is_id_and_source_id(self) -> None:
        c = _citation("cite-1", "doc-1")
        assert _grounding_key(c) == ("cite-1", "doc-1")


class TestFilterToGroundingRefs:
    def test_member_citation_survives(self) -> None:
        grounded = _citation("real", "doc-1")
        result = _filter_to_grounding_refs((grounded,), (grounded,))
        assert result == (grounded,)

    def test_non_member_citation_dropped(self) -> None:
        grounded = _citation("real", "doc-1")
        fabricated = _citation("fabricated", "doc-999")
        result = _filter_to_grounding_refs((grounded, fabricated), (grounded,))
        assert result == (grounded,)

    def test_empty_grounding_refs_drops_everything(self) -> None:
        cited = (_citation("real", "doc-1"),)
        assert _filter_to_grounding_refs(cited, ()) == ()

    def test_empty_cited_returns_empty(self) -> None:
        assert _filter_to_grounding_refs((), (_citation("real", "doc-1"),)) == ()


class TestCheckPolicyViolations:
    def test_must_violation_when_text_missing(self) -> None:
        policy = PolicySpec(rule_id="must-mention-total", kind=PolicyKind.MUST, description="total")
        violations = _check_policy_violations(text="no numbers here", policies=(policy,))
        assert violations == ("must-mention-total",)

    def test_must_satisfied_when_text_present(self) -> None:
        policy = PolicySpec(rule_id="must-mention-total", kind=PolicyKind.MUST, description="total")
        violations = _check_policy_violations(text="the total is 42", policies=(policy,))
        assert violations == ()

    def test_must_not_violation_when_text_present(self) -> None:
        policy = PolicySpec(rule_id="no-internal", kind=PolicyKind.MUST_NOT, description="internal-only")
        violations = _check_policy_violations(text="this is internal-only data", policies=(policy,))
        assert violations == ("no-internal",)

    def test_must_not_satisfied_when_text_absent(self) -> None:
        policy = PolicySpec(rule_id="no-internal", kind=PolicyKind.MUST_NOT, description="internal-only")
        violations = _check_policy_violations(text="public summary", policies=(policy,))
        assert violations == ()

    def test_multiple_policies_collect_all_violations(self) -> None:
        must = PolicySpec(rule_id="must-a", kind=PolicyKind.MUST, description="alpha")
        must_not = PolicySpec(rule_id="no-b", kind=PolicyKind.MUST_NOT, description="beta")
        violations = _check_policy_violations(text="contains beta only", policies=(must, must_not))
        assert set(violations) == {"must-a", "no-b"}
