"""
Citation validation rules.

Provides rules for validating citations in content.
These rules implement the Rule protocol from the validation module.
"""

from __future__ import annotations

from typing import Any

from cemaf.core.types import JSON
from cemaf.validation.protocols import (
    ValidationResult,
    ValidationWarning,
)


class CitationRequiredRule:
    """
    Validate that content has citations.

    IMPORTANT: This rule always returns WARNINGS, never errors.
    Per design decision, missing citations should warn but not block.

    Implements the Rule protocol from validation module.
    """

    def __init__(
        self,
        min_citations: int = 1,
        name: str = "citation_required",
    ) -> None:
        """
        Initialize citation required rule.

        Args:
            min_citations: Minimum number of citations required.
            name: Rule name.
        """
        self._min_citations = min_citations
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """
        Check that data has required citations.

        Accepts:
        - CitedFact: checks citation count
        - CitationRegistry: checks total citations
        - list[CitedFact]: checks each fact
        - dict with "citations" key

        Returns ValidationResult with warnings (never errors).

        Args:
            data: The data to validate.
            context: Optional context for validation.

        Returns:
            ValidationResult with warnings only (always passes).
        """
        # Import here to avoid circular imports
        from cemaf.citation.models import CitationRegistry, CitedFact

        warnings: list[ValidationWarning] = []

        if isinstance(data, CitedFact):
            if data.citation_count < self._min_citations:
                warnings.append(
                    ValidationWarning(
                        code="INSUFFICIENT_CITATIONS",
                        message=(
                            f"Fact has {data.citation_count} citations, minimum is {self._min_citations}"
                        ),
                        field="citations",
                        suggestion=(
                            f"Add at least {self._min_citations - data.citation_count} more citation(s)"
                        ),
                    )
                )

        elif isinstance(data, CitationRegistry):
            uncited = data.get_uncited_facts()
            if uncited:
                for fact in uncited:
                    fact_preview = fact[:50] + "..." if len(fact) > 50 else fact
                    warnings.append(
                        ValidationWarning(
                            code="UNCITED_FACT",
                            message=f"Fact lacks citation: {fact_preview}",
                            suggestion="Add citation for this fact",
                        )
                    )

        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, CitedFact) and item.citation_count < self._min_citations:
                    warnings.append(
                        ValidationWarning(
                            code="INSUFFICIENT_CITATIONS",
                            message=f"Fact {i} has {item.citation_count} citations",
                            field=f"facts[{i}]",
                        )
                    )

        elif isinstance(data, dict) and "citations" in data:
            citations = data.get("citations", [])
            if len(citations) < self._min_citations:
                warnings.append(
                    ValidationWarning(
                        code="INSUFFICIENT_CITATIONS",
                        message=f"Content has {len(citations)} citations, minimum is {self._min_citations}",
                    )
                )

        # Always pass (warnings only, never blocks)
        return ValidationResult.success(warnings=tuple(warnings))


class CitationFormatRule:
    """
    Validate citation format and completeness.

    Checks that citations have required fields like title and URL.
    Implements the Rule protocol from validation module.
    """

    def __init__(
        self,
        require_url: bool = False,
        require_title: bool = True,
        name: str = "citation_format",
    ) -> None:
        """
        Initialize citation format rule.

        Args:
            require_url: Whether URL is required.
            require_title: Whether title is required.
            name: Rule name.
        """
        self._require_url = require_url
        self._require_title = require_title
        self._name = name

    @property
    def name(self) -> str:
        """Unique identifier for this rule."""
        return self._name

    async def check(self, data: Any, context: JSON | None = None) -> ValidationResult:
        """
        Validate citation format.

        Accepts Citation, list[Citation], or CitedFact.
        Returns warnings for format issues.

        Args:
            data: The data to validate.
            context: Optional context for validation.

        Returns:
            ValidationResult with warnings for format issues.
        """
        # Import here to avoid circular imports
        from cemaf.citation.models import Citation, CitedFact

        warnings: list[ValidationWarning] = []

        citations_to_check: list[Citation] = []

        if isinstance(data, Citation):
            citations_to_check = [data]
        elif isinstance(data, CitedFact):
            citations_to_check = list(data.citations)
        elif isinstance(data, list):
            citations_to_check = [c for c in data if isinstance(c, Citation)]

        for citation in citations_to_check:
            if self._require_title and not citation.title:
                warnings.append(
                    ValidationWarning(
                        code="MISSING_TITLE",
                        message=f"Citation {citation.id} is missing title",
                        field="title",
                    )
                )
            if self._require_url and not citation.url:
                warnings.append(
                    ValidationWarning(
                        code="MISSING_URL",
                        message=f"Citation {citation.id} is missing URL",
                        field="url",
                    )
                )
            if citation.confidence < 0 or citation.confidence > 1:
                warnings.append(
                    ValidationWarning(
                        code="INVALID_CONFIDENCE",
                        message=f"Citation {citation.id} has invalid confidence: {citation.confidence}",
                        field="confidence",
                    )
                )

        return ValidationResult.success(warnings=tuple(warnings))
