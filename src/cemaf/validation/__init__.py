"""
Validation module.

Provides business rule validation with pipeline support,
repair suggestions, and multiple built-in rule types.
"""

from cemaf.validation.factories import (
    create_validation_pipeline,
    create_validation_pipeline_from_config,
    create_validation_rule,
    create_validation_rules,
    validation_rule_registry,
)
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
    "create_validation_pipeline",
    "create_validation_pipeline_from_config",
    "create_validation_rule",
    "create_validation_rules",
    "validation_rule_registry",
    # Mock
    "MockValidator",
    "AlwaysPassRule",
    "AlwaysFailRule",
]
