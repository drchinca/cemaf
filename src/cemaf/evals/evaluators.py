"""
Basic evaluators - Deterministic evaluation strategies.

These evaluators don't require LLM calls.
"""

import json
import re
from typing import Any

from cemaf.core.types import JSON
from cemaf.evals.protocols import (
    BaseEvaluator,
    EvalConfig,
    EvalMetric,
    EvalResult,
)


class ExactMatchEvaluator(BaseEvaluator):
    """
    Evaluates exact string match.

    Case sensitivity and whitespace handling configurable.
    """

    def __init__(
        self,
        case_sensitive: bool = True,
        strip_whitespace: bool = True,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._case_sensitive = case_sensitive
        self._strip_whitespace = strip_whitespace

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.EXACT_MATCH

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Check exact match."""
        if expected is None:
            return self._make_result(0.0, "No expected value provided")

        out_str = str(output)
        exp_str = str(expected)

        if self._strip_whitespace:
            out_str = out_str.strip()
            exp_str = exp_str.strip()

        if not self._case_sensitive:
            out_str = out_str.lower()
            exp_str = exp_str.lower()

        matches = out_str == exp_str

        return self._make_result(
            score=1.0 if matches else 0.0,
            reason="Exact match" if matches else "Output does not match expected",
            expected=expected,
            actual=output,
        )


class ContainsEvaluator(BaseEvaluator):
    """
    Evaluates if output contains expected substring(s).

    Can check for multiple substrings with AND/OR logic.
    """

    def __init__(
        self,
        case_sensitive: bool = False,
        require_all: bool = True,  # AND vs OR for multiple
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._case_sensitive = case_sensitive
        self._require_all = require_all

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.CONTAINS

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Check if output contains expected substring(s)."""
        if expected is None:
            return self._make_result(0.0, "No expected value provided")

        out_str = str(output)

        # Handle single string or list of strings
        if isinstance(expected, str):
            substrings = [expected]
        elif isinstance(expected, (list, tuple)):
            substrings = [str(s) for s in expected]
        else:
            substrings = [str(expected)]

        if not self._case_sensitive:
            out_str = out_str.lower()
            substrings = [s.lower() for s in substrings]

        found = [s for s in substrings if s in out_str]
        not_found = [s for s in substrings if s not in out_str]

        if self._require_all:
            # AND logic
            score = len(found) / len(substrings) if substrings else 0.0
            passed = len(not_found) == 0
            reason = "All substrings found" if passed else f"Missing: {not_found}"
        else:
            # OR logic
            score = 1.0 if found else 0.0
            passed = len(found) > 0
            reason = f"Found: {found}" if passed else "No substrings found"

        return self._make_result(
            score=score,
            reason=reason,
            expected=expected,
            actual=output,
        )


class RegexEvaluator(BaseEvaluator):
    """
    Evaluates output against regex pattern(s).
    """

    def __init__(
        self,
        flags: int = 0,  # re.IGNORECASE, etc.
        require_all: bool = True,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._flags = flags
        self._require_all = require_all

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.CUSTOM

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Check if output matches regex pattern(s)."""
        if expected is None:
            return self._make_result(0.0, "No pattern provided")

        out_str = str(output)

        # Handle single pattern or list
        if isinstance(expected, str):
            patterns = [expected]
        elif isinstance(expected, (list, tuple)):
            patterns = [str(p) for p in expected]
        else:
            patterns = [str(expected)]

        matched: list[str] = []
        not_matched: list[str] = []

        for pattern in patterns:
            try:
                if re.search(pattern, out_str, self._flags):
                    matched.append(pattern)
                else:
                    not_matched.append(pattern)
            except re.error as e:
                return self._make_result(0.0, f"Invalid regex: {e}")

        if self._require_all:
            score = len(matched) / len(patterns) if patterns else 0.0
        else:
            score = 1.0 if matched else 0.0

        return self._make_result(
            score=score,
            reason=f"Matched {len(matched)}/{len(patterns)} patterns",
            expected=patterns,
            actual=output,
        )


class LengthEvaluator(BaseEvaluator):
    """
    Evaluates output length (characters or words).
    """

    def __init__(
        self,
        min_length: int | None = None,
        max_length: int | None = None,
        unit: str = "chars",  # "chars" or "words"
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._min = min_length
        self._max = max_length
        self._unit = unit

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.LENGTH

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Check if output length is within bounds."""
        out_str = str(output)

        length = len(out_str.split()) if self._unit == "words" else len(out_str)

        issues: list[str] = []

        if self._min is not None and length < self._min:
            issues.append(f"too short ({length} < {self._min})")

        if self._max is not None and length > self._max:
            issues.append(f"too long ({length} > {self._max})")

        passed = len(issues) == 0

        # Calculate score based on how close to acceptable range
        if passed:
            score = 1.0
        elif self._min and length < self._min:
            score = length / self._min
        elif self._max and length > self._max:
            score = self._max / length
        else:
            score = 0.0

        return self._make_result(
            score=score,
            reason=f"Length: {length} {self._unit}" + (f" ({', '.join(issues)})" if issues else ""),
            expected=f"{self._min or 0}-{self._max or '∞'} {self._unit}",
            actual=length,
        )


class JSONSchemaEvaluator(BaseEvaluator):
    """
    Evaluates if output is valid JSON matching a schema.
    """

    def __init__(
        self,
        schema: JSON | None = None,
        config: EvalConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._schema = schema

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.JSON_VALID if not self._schema else EvalMetric.SCHEMA_VALID

    async def evaluate(
        self,
        output: Any,
        expected: Any | None = None,
        context: JSON | None = None,
    ) -> EvalResult:
        """Check if output is valid JSON (and matches schema if provided)."""
        # Use provided schema or expected as schema
        schema = self._schema or expected

        # Try to parse as JSON
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError as e:
                return self._make_result(
                    score=0.0,
                    reason=f"Invalid JSON: {e}",
                    actual=output[:100] + "..." if len(str(output)) > 100 else output,
                )
        else:
            parsed = output

        # If no schema, just validate JSON
        if not schema:
            return self._make_result(
                score=1.0,
                reason="Valid JSON",
                actual=type(parsed).__name__,
            )

        # Simple schema validation (type checking)
        # For full JSON Schema validation, use jsonschema library
        schema_type = schema.get("type") if isinstance(schema, dict) else None

        type_map = {
            "object": dict,
            "array": list,
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "null": type(None),
        }

        if schema_type and schema_type in type_map:
            expected_type = type_map[schema_type]
            if not isinstance(parsed, expected_type):
                return self._make_result(
                    score=0.0,
                    reason=f"Type mismatch: expected {schema_type}, got {type(parsed).__name__}",
                    expected=schema_type,
                    actual=type(parsed).__name__,
                )

        # Check required properties for objects
        if isinstance(parsed, dict) and isinstance(schema, dict):
            required = schema.get("required", [])
            missing = [r for r in required if r not in parsed]
            if missing:
                return self._make_result(
                    score=1 - len(missing) / len(required),
                    reason=f"Missing required properties: {missing}",
                    expected=required,
                    actual=list(parsed.keys()),
                )

        return self._make_result(
            score=1.0,
            reason="Matches schema",
            expected=schema,
        )
