"""
Validation module.

Provides business rule validation with pipeline support,
repair suggestions, and multiple built-in rule types.
"""

from cemaf.validation.mock import AlwaysFailRule, AlwaysPassRule, MockValidator
from cemaf.validation.pipeline import ValidationPipeline
from cemaf.validation.protocols import (
    Rule,
    ValidationError,
    ValidationResult,
    ValidationSeverity,
    ValidationWarning,
    Validator,
)
from cemaf.validation.rules import (
    CustomRule,
    LengthRule,
    RangeRule,
    RegexRule,
    RequiredFieldsRule,
    SchemaRule,
)

__all__ = [
    # Protocols
    "Rule",
    "Validator",
    "ValidationResult",
    "ValidationError",
    "ValidationWarning",
    "ValidationSeverity",
    # Rules
    "SchemaRule",
    "LengthRule",
    "RegexRule",
    "RangeRule",
    "RequiredFieldsRule",
    "CustomRule",
    # Pipeline
    "ValidationPipeline",
    # Mock
    "MockValidator",
    "AlwaysPassRule",
    "AlwaysFailRule",
]
