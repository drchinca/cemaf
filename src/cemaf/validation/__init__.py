"""
Validation module.

Provides business rule validation with pipeline support,
repair suggestions, and multiple built-in rule types.
"""

from cemaf.validation.protocols import (
    Rule,
    Validator,
    ValidationResult,
    ValidationError,
    ValidationWarning,
    ValidationSeverity,
)
from cemaf.validation.rules import (
    SchemaRule,
    LengthRule,
    RegexRule,
    RangeRule,
    RequiredFieldsRule,
    CustomRule,
)
from cemaf.validation.pipeline import ValidationPipeline
from cemaf.validation.mock import MockValidator, AlwaysPassRule, AlwaysFailRule

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

