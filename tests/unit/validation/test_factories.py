"""Tests for validation factory composition roots."""

from cemaf.config.protocols import Settings, ValidationSettings
from cemaf.validation import (
    ValidationResult,
    create_validation_pipeline,
    create_validation_pipeline_from_config,
    create_validation_rule,
    validation_rule_registry,
)
from cemaf.validation.rules import LengthRule, RequiredFieldsRule


class CustomRule:
    @property
    def name(self) -> str:
        return "custom"

    async def check(self, data, context=None):  # noqa: ANN001, ANN201
        return ValidationResult.success()


def test_create_validation_rule_uses_builtin_registry() -> None:
    rule = create_validation_rule("length", min_length=2, max_length=5, field="name")

    assert isinstance(rule, LengthRule)
    assert rule.name == "length"


def test_create_validation_rule_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomRule()

    validation_rule_registry.register(backend="custom-rule", factory=_factory)

    rule = create_validation_rule("custom-rule", mode="strict")

    assert isinstance(rule, CustomRule)
    assert created["args"]["mode"] == "strict"


def test_create_validation_pipeline_accepts_rule_specs() -> None:
    pipeline = create_validation_pipeline(
        rule_specs=[
            {"type": "required_fields", "fields": ("id", "name")},
            {"type": "length", "min_length": 1},
        ]
    )

    assert len(pipeline.rules) == 2
    assert isinstance(pipeline.rules[0], RequiredFieldsRule)
    assert isinstance(pipeline.rules[1], LengthRule)


def test_create_validation_pipeline_from_config_uses_settings() -> None:
    settings = Settings(validation=ValidationSettings(fail_fast=True, strict_mode=True))

    pipeline = create_validation_pipeline_from_config(settings=settings)

    assert pipeline._fail_fast is True  # noqa: SLF001
