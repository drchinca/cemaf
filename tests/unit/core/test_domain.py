"""Tests for domain context models."""

import pytest

from cemaf.core.domain import DomainContext
from cemaf.core.types import DomainID, TenantID


class TestDomainContext:
    """Tests for DomainContext frozen Pydantic model."""

    def test_create_minimal(self) -> None:
        ctx = DomainContext(
            domain_id=DomainID("marketing"),
            tenant_id=TenantID("acme-corp"),
        )
        assert ctx.domain_id == "marketing"
        assert ctx.tenant_id == "acme-corp"
        assert ctx.business_rules == ()
        assert ctx.required_citation_style == "inline"

    def test_create_full(self) -> None:
        ctx = DomainContext(
            domain_id=DomainID("legal"),
            tenant_id=TenantID("lawfirm"),
            business_rules=("must cite statute", "no informal language"),
            vocabulary_constraints=("defendant", "plaintiff"),
            required_citation_style="footnote",
            quality_thresholds={"accuracy": 0.95, "completeness": 0.8},
        )
        assert len(ctx.business_rules) == 2
        assert ctx.required_citation_style == "footnote"

    def test_frozen(self) -> None:
        ctx = DomainContext(
            domain_id=DomainID("test"),
            tenant_id=TenantID("t"),
        )
        with pytest.raises(Exception):
            ctx.domain_id = DomainID("changed")  # type: ignore[misc]

    def test_with_rules(self) -> None:
        ctx = DomainContext(
            domain_id=DomainID("test"),
            tenant_id=TenantID("t"),
            business_rules=("rule1",),
        )
        updated = ctx.with_rules("rule2", "rule3")
        assert updated.business_rules == ("rule1", "rule2", "rule3")
        assert ctx.business_rules == ("rule1",)  # original unchanged

    def test_with_vocabulary(self) -> None:
        ctx = DomainContext(
            domain_id=DomainID("test"),
            tenant_id=TenantID("t"),
        )
        updated = ctx.with_vocabulary("term1", "term2")
        assert updated.vocabulary_constraints == ("term1", "term2")

    def test_meets_quality_threshold(self) -> None:
        ctx = DomainContext(
            domain_id=DomainID("test"),
            tenant_id=TenantID("t"),
            quality_thresholds={"accuracy": 0.9},
        )
        assert ctx.meets_quality(metric="accuracy", value=0.95) is True
        assert ctx.meets_quality(metric="accuracy", value=0.85) is False
        assert ctx.meets_quality(metric="unknown", value=0.1) is True  # no threshold

    def test_serialization(self) -> None:
        ctx = DomainContext(
            domain_id=DomainID("test"),
            tenant_id=TenantID("t"),
            business_rules=("rule1",),
        )
        data = ctx.model_dump()
        restored = DomainContext.model_validate(data)
        assert restored == ctx
