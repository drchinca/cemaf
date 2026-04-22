"""Domain context for multi-tenant, domain-scoped operations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from cemaf.core.types import DomainID, TenantID


class DomainContext(BaseModel, frozen=True):
    """Immutable domain context for business-scoped LLM operations."""

    domain_id: DomainID
    tenant_id: TenantID
    business_rules: tuple[str, ...] = ()
    vocabulary_constraints: tuple[str, ...] = ()
    required_citation_style: str = "inline"
    quality_thresholds: dict[str, float] = Field(default_factory=dict)

    def with_rules(self, *rules: str) -> DomainContext:
        """Return new context with additional business rules."""
        return self.model_copy(
            update={"business_rules": self.business_rules + rules},
        )

    def with_vocabulary(self, *terms: str) -> DomainContext:
        """Return new context with additional vocabulary constraints."""
        return self.model_copy(
            update={"vocabulary_constraints": self.vocabulary_constraints + terms},
        )

    def meets_quality(self, metric: str, value: float) -> bool:
        """Check if a value meets the quality threshold for a metric."""
        threshold = self.quality_thresholds.get(metric)
        if threshold is None:
            return True
        return value >= threshold
