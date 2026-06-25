"""
Factory functions for validation components.

Provides convenient ways to create validation pipelines with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. Add your own validation rules
    and compose them into custom pipelines.
"""

import os
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.validation.pipeline import ValidationPipeline
from cemaf.validation.protocols import Rule
from cemaf.validation.rules import LengthRule, RangeRule, RegexRule, RequiredFieldsRule, SchemaRule

validation_rule_registry: ProviderRegistry[Rule] = ProviderRegistry(name="validation_rule")


def _create_schema_rule(**kwargs: Any) -> Rule:
    schema = kwargs.get("schema")
    if schema is None:
        raise ValueError("schema validation rule requires schema.")
    return SchemaRule(schema=schema, name=kwargs.get("name"))


def _create_length_rule(**kwargs: Any) -> Rule:
    return LengthRule(
        min_length=kwargs.get("min_length"),
        max_length=kwargs.get("max_length"),
        field=kwargs.get("field"),
        name=str(kwargs.get("name", "length")),
    )


def _create_regex_rule(**kwargs: Any) -> Rule:
    pattern = kwargs.get("pattern")
    if pattern is None:
        raise ValueError("regex validation rule requires pattern.")
    return RegexRule(
        pattern=str(pattern),
        field=kwargs.get("field"),
        message=kwargs.get("message"),
        name=str(kwargs.get("name", "regex")),
    )


def _create_range_rule(**kwargs: Any) -> Rule:
    return RangeRule(
        min_value=kwargs.get("min_value"),
        max_value=kwargs.get("max_value"),
        field=kwargs.get("field"),
        name=str(kwargs.get("name", "range")),
    )


def _create_required_fields_rule(**kwargs: Any) -> Rule:
    return RequiredFieldsRule(
        fields=tuple(kwargs.get("fields", ())),
        name=str(kwargs.get("name", "required_fields")),
    )


validation_rule_registry.register(backend="schema", factory=_create_schema_rule)
validation_rule_registry.register(backend="length", factory=_create_length_rule)
validation_rule_registry.register(backend="regex", factory=_create_regex_rule)
validation_rule_registry.register(backend="range", factory=_create_range_rule)
validation_rule_registry.register(backend="required_fields", factory=_create_required_fields_rule)


def create_validation_rule(rule_type: str, **rule_options: Any) -> Rule:
    """Create a validation rule from a registered rule backend."""
    return validation_rule_registry.create(backend=rule_type, **rule_options)


def create_validation_rules(rule_specs: list[dict[str, Any]] | None = None) -> list[Rule]:
    """Create validation rules from typed rule specs."""
    created: list[Rule] = []
    for spec in rule_specs or []:
        spec_copy = dict(spec)
        rule_type = str(spec_copy.pop("type"))
        created.append(create_validation_rule(rule_type, **spec_copy))
    return created


def create_validation_pipeline(
    rules: list[Rule] | None = None,
    rule_specs: list[dict[str, Any]] | None = None,
    strict_mode: bool = False,
    fail_fast: bool = False,
) -> ValidationPipeline:
    """
    Factory for ValidationPipeline with sensible defaults.

    Args:
        rules: List of validation rules to apply
        rule_specs: Declarative rule specs resolved through validation_rule_registry
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
    # ValidationPipeline only accepts fail_fast, not rules or strict_mode
    # Rules are added via add_rule() or add_rules() methods
    pipeline = ValidationPipeline(fail_fast=fail_fast)
    resolved_rules = [*(rules or []), *create_validation_rules(rule_specs)]
    if resolved_rules:
        pipeline.add_rules(*resolved_rules)
    return pipeline


def create_validation_pipeline_from_config(
    rules: list[Rule] | None = None,
    rule_specs: list[dict[str, Any]] | None = None,
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
    cfg = settings or load_settings_from_env_sync()

    strict_mode = os.getenv("CEMAF_VALIDATION_STRICT_MODE", str(cfg.validation.strict_mode)).lower() == "true"
    fail_fast = os.getenv("CEMAF_VALIDATION_FAIL_FAST", str(cfg.validation.fail_fast)).lower() == "true"

    return create_validation_pipeline(
        rules=rules,
        rule_specs=rule_specs,
        strict_mode=strict_mode,
        fail_fast=fail_fast,
    )
