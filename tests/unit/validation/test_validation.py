"""Tests for validation module."""

from __future__ import annotations

from pydantic import BaseModel

from cemaf.validation.mock import (
    AlwaysFailRule,
    AlwaysPassRule,
    MockValidator,
)
from cemaf.validation.pipeline import ValidationPipeline
from cemaf.validation.protocols import (
    ValidationError,
    ValidationResult,
    ValidationWarning,
)
from cemaf.validation.rules import (
    CustomRule,
    LengthRule,
    RangeRule,
    RegexRule,
    RequiredFieldsRule,
    SchemaRule,
)

# =============================================================================
# ValidationResult Tests
# =============================================================================


class TestValidationResult:
    """Tests for ValidationResult."""

    def test_success_factory(self) -> None:
        """Test creating a successful result."""
        result = ValidationResult.success()
        assert result.passed is True
        assert result.errors == ()
        assert result.warnings == ()

    def test_success_with_warnings(self) -> None:
        """Test successful result with warnings."""
        warnings = (ValidationWarning(code="WARN", message="Warning"),)
        result = ValidationResult.success(warnings=warnings)
        assert result.passed is True
        assert len(result.warnings) == 1

    def test_failure_factory(self) -> None:
        """Test creating a failed result."""
        errors = (ValidationError(code="ERR", message="Error"),)
        result = ValidationResult.failure(errors=errors)
        assert result.passed is False
        assert len(result.errors) == 1

    def test_error_factory(self) -> None:
        """Test creating a single-error result."""
        result = ValidationResult.error(
            code="ERR001",
            message="Something went wrong",
            field="name",
            suggestion="Fix it",
        )
        assert result.passed is False
        assert len(result.errors) == 1
        assert result.errors[0].code == "ERR001"
        assert result.errors[0].suggestion == "Fix it"
        assert result.suggestions == ("Fix it",)

    def test_merge_results(self) -> None:
        """Test merging two results."""
        result1 = ValidationResult.error("E1", "Error 1")
        result2 = ValidationResult.error("E2", "Error 2")
        merged = result1.merge(result2)

        assert merged.passed is False
        assert len(merged.errors) == 2

    def test_merge_success_results(self) -> None:
        """Test merging successful results."""
        result1 = ValidationResult.success()
        result2 = ValidationResult.success()
        merged = result1.merge(result2)

        assert merged.passed is True


# =============================================================================
# LengthRule Tests
# =============================================================================


class TestLengthRule:
    """Tests for LengthRule."""

    async def test_min_length_pass(self) -> None:
        """Test minimum length passes."""
        rule = LengthRule(min_length=3)
        result = await rule.check("hello")
        assert result.passed is True

    async def test_min_length_fail(self) -> None:
        """Test minimum length fails."""
        rule = LengthRule(min_length=10)
        result = await rule.check("hello")
        assert result.passed is False
        assert result.errors[0].code == "LENGTH_TOO_SHORT"

    async def test_max_length_pass(self) -> None:
        """Test maximum length passes."""
        rule = LengthRule(max_length=10)
        result = await rule.check("hello")
        assert result.passed is True

    async def test_max_length_fail(self) -> None:
        """Test maximum length fails."""
        rule = LengthRule(max_length=3)
        result = await rule.check("hello")
        assert result.passed is False
        assert result.errors[0].code == "LENGTH_TOO_LONG"

    async def test_both_bounds(self) -> None:
        """Test with both min and max bounds."""
        rule = LengthRule(min_length=3, max_length=10)

        result = await rule.check("hello")
        assert result.passed is True

        result = await rule.check("hi")
        assert result.passed is False

        result = await rule.check("hello world!")
        assert result.passed is False

    async def test_list_length(self) -> None:
        """Test length of list."""
        rule = LengthRule(min_length=2)
        result = await rule.check([1, 2, 3])
        assert result.passed is True

    async def test_non_sized_type(self) -> None:
        """Test with type that has no length."""
        rule = LengthRule(min_length=1)
        result = await rule.check(42)
        assert result.passed is False
        assert "LENGTH_NOT_SUPPORTED" in result.errors[0].code


# =============================================================================
# RegexRule Tests
# =============================================================================


class TestRegexRule:
    """Tests for RegexRule."""

    async def test_pattern_match(self) -> None:
        """Test matching pattern."""
        rule = RegexRule(pattern=r"^\d{3}-\d{4}$")
        result = await rule.check("123-4567")
        assert result.passed is True

    async def test_pattern_no_match(self) -> None:
        """Test non-matching pattern."""
        rule = RegexRule(pattern=r"^\d+$")
        result = await rule.check("abc")
        assert result.passed is False
        assert result.errors[0].code == "REGEX_NO_MATCH"

    async def test_custom_message(self) -> None:
        """Test custom error message."""
        rule = RegexRule(
            pattern=r"^[a-z]+$",
            message="Only lowercase letters allowed",
        )
        result = await rule.check("ABC")
        assert "lowercase" in result.errors[0].message

    async def test_non_string_type(self) -> None:
        """Test with non-string input."""
        rule = RegexRule(pattern=r"\d+")
        result = await rule.check(123)
        assert result.passed is False
        assert result.errors[0].code == "REGEX_TYPE_ERROR"


# =============================================================================
# RangeRule Tests
# =============================================================================


class TestRangeRule:
    """Tests for RangeRule."""

    async def test_within_range(self) -> None:
        """Test value within range."""
        rule = RangeRule(min_value=0, max_value=100)
        result = await rule.check(50)
        assert result.passed is True

    async def test_below_minimum(self) -> None:
        """Test value below minimum."""
        rule = RangeRule(min_value=10)
        result = await rule.check(5)
        assert result.passed is False
        assert result.errors[0].code == "RANGE_TOO_LOW"

    async def test_above_maximum(self) -> None:
        """Test value above maximum."""
        rule = RangeRule(max_value=10)
        result = await rule.check(15)
        assert result.passed is False
        assert result.errors[0].code == "RANGE_TOO_HIGH"

    async def test_float_value(self) -> None:
        """Test with float value."""
        rule = RangeRule(min_value=0.0, max_value=1.0)
        result = await rule.check(0.5)
        assert result.passed is True

    async def test_non_numeric_type(self) -> None:
        """Test with non-numeric input."""
        rule = RangeRule(min_value=0)
        result = await rule.check("not a number")
        assert result.passed is False
        assert result.errors[0].code == "RANGE_TYPE_ERROR"


# =============================================================================
# RequiredFieldsRule Tests
# =============================================================================


class TestRequiredFieldsRule:
    """Tests for RequiredFieldsRule."""

    async def test_all_fields_present(self) -> None:
        """Test when all required fields are present."""
        rule = RequiredFieldsRule(fields=["name", "email"])
        result = await rule.check({"name": "John", "email": "john@example.com"})
        assert result.passed is True

    async def test_missing_fields(self) -> None:
        """Test when required fields are missing."""
        rule = RequiredFieldsRule(fields=["name", "email"])
        result = await rule.check({"name": "John"})
        assert result.passed is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "email"

    async def test_non_dict_input(self) -> None:
        """Test with non-dict input."""
        rule = RequiredFieldsRule(fields=["name"])
        result = await rule.check("not a dict")
        assert result.passed is False
        assert "TYPE_ERROR" in result.errors[0].code


# =============================================================================
# SchemaRule Tests
# =============================================================================


class TestSchemaRule:
    """Tests for SchemaRule."""

    async def test_valid_schema(self) -> None:
        """Test valid data against schema."""

        class UserSchema(BaseModel):
            name: str
            age: int

        rule = SchemaRule(UserSchema)
        result = await rule.check({"name": "John", "age": 30})
        assert result.passed is True

    async def test_invalid_schema(self) -> None:
        """Test invalid data against schema."""

        class UserSchema(BaseModel):
            name: str
            age: int

        rule = SchemaRule(UserSchema)
        result = await rule.check({"name": "John", "age": "not a number"})
        assert result.passed is False
        assert result.errors[0].code == "SCHEMA_INVALID"

    async def test_rule_name(self) -> None:
        """Test schema rule name."""

        class UserSchema(BaseModel):
            name: str

        rule = SchemaRule(UserSchema)
        assert "UserSchema" in rule.name


# =============================================================================
# CustomRule Tests
# =============================================================================


class TestCustomRule:
    """Tests for CustomRule."""

    async def test_custom_validation(self) -> None:
        """Test custom validation function."""

        async def check_even(data: int, context: dict | None) -> ValidationResult:
            if data % 2 == 0:
                return ValidationResult.success()
            return ValidationResult.error("NOT_EVEN", "Value must be even")

        rule = CustomRule(check_fn=check_even, name="even_check")

        result = await rule.check(4)
        assert result.passed is True

        result = await rule.check(5)
        assert result.passed is False


# =============================================================================
# ValidationPipeline Tests
# =============================================================================


class TestValidationPipeline:
    """Tests for ValidationPipeline."""

    async def test_empty_pipeline(self) -> None:
        """Test empty pipeline passes."""
        pipeline = ValidationPipeline()
        result = await pipeline.run("any data")
        assert result.passed is True

    async def test_single_rule(self) -> None:
        """Test pipeline with single rule."""
        pipeline = ValidationPipeline()
        pipeline.add_rule(LengthRule(min_length=5))

        result = await pipeline.run("hello world")
        assert result.passed is True

        result = await pipeline.run("hi")
        assert result.passed is False

    async def test_multiple_rules(self) -> None:
        """Test pipeline with multiple rules."""
        pipeline = ValidationPipeline()
        pipeline.add_rule(LengthRule(min_length=3))
        pipeline.add_rule(RegexRule(pattern=r"^[a-z]+$"))

        result = await pipeline.run("hello")
        assert result.passed is True

        result = await pipeline.run("hi")  # Too short
        assert result.passed is False

    async def test_fail_fast_mode(self) -> None:
        """Test fail-fast stops on first error."""
        pipeline = ValidationPipeline(fail_fast=True)
        pipeline.add_rule(AlwaysFailRule(error_code="FIRST"))
        pipeline.add_rule(AlwaysFailRule(error_code="SECOND"))

        result = await pipeline.run("data")
        assert result.passed is False
        assert len(result.errors) == 1
        assert result.errors[0].code == "FIRST"

    async def test_collect_all_mode(self) -> None:
        """Test collect-all gathers all errors."""
        pipeline = ValidationPipeline(fail_fast=False)
        pipeline.add_rule(AlwaysFailRule(error_code="FIRST"))
        pipeline.add_rule(AlwaysFailRule(error_code="SECOND"))

        result = await pipeline.run("data")
        assert result.passed is False
        assert len(result.errors) == 2

    async def test_method_chaining(self) -> None:
        """Test fluent method chaining."""
        pipeline = (
            ValidationPipeline().add_rule(LengthRule(min_length=1)).add_rule(LengthRule(max_length=100))
        )
        assert len(pipeline) == 2

    async def test_validate_alias(self) -> None:
        """Test validate() is alias for run()."""
        pipeline = ValidationPipeline()
        pipeline.add_rule(AlwaysPassRule())

        result = await pipeline.validate("data")
        assert result.passed is True


# =============================================================================
# Mock Tests
# =============================================================================


class TestMockValidator:
    """Tests for MockValidator."""

    async def test_mock_pass(self) -> None:
        """Test mock validator passes."""
        validator = MockValidator(should_pass=True)
        result = await validator.validate("data")
        assert result.passed is True

    async def test_mock_fail(self) -> None:
        """Test mock validator fails."""
        validator = MockValidator(should_pass=False)
        result = await validator.validate("data")
        assert result.passed is False

    async def test_records_calls(self) -> None:
        """Test mock records validation calls."""
        validator = MockValidator()
        await validator.validate("data1")
        await validator.validate("data2", {"key": "value"})

        assert validator.call_count == 2
        assert validator.calls[0] == ("data1", None)
        assert validator.calls[1] == ("data2", {"key": "value"})

    async def test_reset(self) -> None:
        """Test mock reset clears calls."""
        validator = MockValidator()
        await validator.validate("data")
        validator.reset()

        assert validator.call_count == 0


class TestAlwaysPassRule:
    """Tests for AlwaysPassRule."""

    async def test_always_passes(self) -> None:
        """Test rule always passes."""
        rule = AlwaysPassRule()
        result = await rule.check(None)
        assert result.passed is True


class TestAlwaysFailRule:
    """Tests for AlwaysFailRule."""

    async def test_always_fails(self) -> None:
        """Test rule always fails."""
        rule = AlwaysFailRule()
        result = await rule.check(None)
        assert result.passed is False

    async def test_custom_error(self) -> None:
        """Test custom error code and message."""
        rule = AlwaysFailRule(error_code="CUSTOM", error_message="Custom error")
        result = await rule.check(None)
        assert result.errors[0].code == "CUSTOM"
        assert result.errors[0].message == "Custom error"
