"""
Factory functions for validation components.

Provides convenient ways to create validation pipelines with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. Add your own validation rules
    and compose them into custom pipelines.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.validation.pipeline import ValidationPipeline
from cemaf.validation.protocols import ValidationRule


def create_validation_pipeline(
    rules: list[ValidationRule] | None = None,
    strict_mode: bool = False,
    fail_fast: bool = False,
) -> ValidationPipeline:
    """
    Factory for ValidationPipeline with sensible defaults.

    Args:
        rules: List of validation rules to apply
        strict_mode: If True, warnings are treated as errors
        fail_fast: If True, stop on first validation failure

    Returns:
        Configured ValidationPipeline instance

    Example:
        # Empty pipeline (add rules later)
        pipeline = create_validation_pipeline()

        # With rules
        from cemaf.validation.rules import SchemaValidationRule
        rules = [SchemaValidationRule(schema)]
        pipeline = create_validation_pipeline(rules=rules, strict_mode=True)
    """
    return ValidationPipeline(
        rules=rules or [],
        strict_mode=strict_mode,
        fail_fast=fail_fast,
    )


def create_validation_pipeline_from_config(
    rules: list[ValidationRule] | None = None,
    settings: Settings | None = None,
) -> ValidationPipeline:
    """
    Create ValidationPipeline from environment configuration.

    Reads from environment variables:
    - CEMAF_VALIDATION_STRICT_MODE: Treat warnings as errors (default: False)
    - CEMAF_VALIDATION_FAIL_FAST: Stop on first failure (default: False)

    Args:
        rules: List of validation rules (overrides default rules)

    Returns:
        Configured ValidationPipeline instance

    Example:
        # From environment
        pipeline = create_validation_pipeline_from_config()

        # With custom rules
        pipeline = create_validation_pipeline_from_config(rules=[my_rule])
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    strict_mode = os.getenv("CEMAF_VALIDATION_STRICT_MODE", "false").lower() == "true"
    fail_fast = os.getenv("CEMAF_VALIDATION_FAIL_FAST", "false").lower() == "true"

    return create_validation_pipeline(
        rules=rules,
        strict_mode=strict_mode,
        fail_fast=fail_fast,
    )
