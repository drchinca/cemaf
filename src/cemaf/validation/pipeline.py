"""
Validation pipeline for chaining multiple rules.
"""

from typing import Any, Self

from cemaf.core.types import JSON
from cemaf.validation.protocols import Rule, ValidationResult


class ValidationPipeline:
    """
    Chain multiple validation rules.

    Supports fail-fast (stop on first error) or collect-all modes.
    Rules are executed in the order they were added.
    """

    def __init__(
        self,
        fail_fast: bool = False,
        name: str = "pipeline",
    ) -> None:
        """
        Initialize validation pipeline.

        Args:
            fail_fast: Stop validation on first error.
            name: Pipeline name.
        """
        self._rules: list[Rule] = []
        self._fail_fast = fail_fast
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def rules(self) -> tuple[Rule, ...]:
        """Get all rules in the pipeline."""
        return tuple(self._rules)

    def add_rule(self, rule: Rule) -> Self:
        """
        Add a rule to the pipeline.

        Args:
            rule: Rule to add.

        Returns:
            Self for method chaining.
        """
        self._rules.append(rule)
        return self

    def add_rules(self, *rules: Rule) -> Self:
        """
        Add multiple rules to the pipeline.

        Args:
            rules: Rules to add.

        Returns:
            Self for method chaining.
        """
        self._rules.extend(rules)
        return self

    async def run(
        self,
        data: Any,
        context: JSON | None = None,
    ) -> ValidationResult:
        """
        Run all rules against the data.

        Args:
            data: Data to validate.
            context: Optional context for validation.

        Returns:
            Merged ValidationResult from all rules.
        """
        if not self._rules:
            return ValidationResult.success()

        result = ValidationResult.success()

        for rule in self._rules:
            rule_result = await rule.check(data, context)
            result = result.merge(rule_result)

            if self._fail_fast and not rule_result.passed:
                break

        return result

    async def validate(
        self,
        data: Any,
        context: JSON | None = None,
    ) -> ValidationResult:
        """
        Alias for run() to match Validator protocol.

        Args:
            data: Data to validate.
            context: Optional context for validation.

        Returns:
            Merged ValidationResult from all rules.
        """
        return await self.run(data, context)

    def clear(self) -> Self:
        """
        Remove all rules from the pipeline.

        Returns:
            Self for method chaining.
        """
        self._rules.clear()
        return self

    def __len__(self) -> int:
        """Return number of rules in the pipeline."""
        return len(self._rules)
