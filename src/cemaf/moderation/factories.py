"""
Factory functions for moderation components.

Provides convenient ways to create moderation pipelines with sensible defaults
while maintaining dependency injection principles.
"""

import os
from typing import Any, cast

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.events.protocols import EventBus
from cemaf.moderation.gates import CompositeGate, PostFlightGate, PreFlightGate
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.moderation.protocols import ModerationGate, ModerationRule, ModerationSeverity
from cemaf.moderation.rules import KeywordRule, LengthRule, PatternRule, PIIRule

moderation_rule_registry: ProviderRegistry[ModerationRule] = ProviderRegistry(name="moderation_rule")
moderation_gate_registry: ProviderRegistry[ModerationGate] = ProviderRegistry(name="moderation_gate")


def _create_keyword_rule(**kwargs: Any) -> ModerationRule:
    return KeywordRule(
        blocked_words=tuple(kwargs.get("blocked_words", ())),
        whole_word_only=bool(kwargs.get("whole_word_only", True)),
        severity=kwargs.get("severity", "error"),
    )


def _create_pii_rule(**kwargs: Any) -> ModerationRule:
    return PIIRule(
        detect_email=bool(kwargs.get("detect_email", True)),
        detect_phone=bool(kwargs.get("detect_phone", True)),
        detect_ssn=bool(kwargs.get("detect_ssn", True)),
        detect_credit_card=bool(kwargs.get("detect_credit_card", True)),
        severity=kwargs.get("severity", "error"),
    )


def _create_length_rule(**kwargs: Any) -> ModerationRule:
    return LengthRule(
        min_length=kwargs.get("min_length"),
        max_length=kwargs.get("max_length"),
        severity=kwargs.get("severity", "warning"),
    )


def _create_pattern_rule(**kwargs: Any) -> ModerationRule:
    return PatternRule(
        pattern=str(kwargs["pattern"]),
        violation_code=str(kwargs["violation_code"]),
        violation_message=str(kwargs["violation_message"]),
        severity=kwargs.get("severity", "error"),
        suggestion=kwargs.get("suggestion"),
    )


def _create_pre_flight_gate(**kwargs: Any) -> ModerationGate:
    return cast(
        ModerationGate,
        PreFlightGate(
            rules=list(kwargs.get("rules") or []),
            fail_fast=bool(kwargs.get("fail_fast", True)),
            name=str(kwargs.get("name", "pre_flight")),
        ),
    )


def _create_post_flight_gate(**kwargs: Any) -> ModerationGate:
    return cast(
        ModerationGate,
        PostFlightGate(
            rules=list(kwargs.get("rules") or []),
            redact_on_violation=bool(kwargs.get("redact_on_violation", False)),
            name=str(kwargs.get("name", "post_flight")),
        ),
    )


def _create_composite_gate(**kwargs: Any) -> ModerationGate:
    return cast(
        ModerationGate,
        CompositeGate(
            gates=list(kwargs.get("gates") or []),
            fail_fast=bool(kwargs.get("fail_fast", True)),
            name=str(kwargs.get("name", "composite")),
        ),
    )


moderation_rule_registry.register(backend="keyword", factory=_create_keyword_rule)
moderation_rule_registry.register(backend="pii", factory=_create_pii_rule)
moderation_rule_registry.register(backend="length", factory=_create_length_rule)
moderation_rule_registry.register(backend="pattern", factory=_create_pattern_rule)
moderation_gate_registry.register(backend="pre_flight", factory=_create_pre_flight_gate)
moderation_gate_registry.register(backend="post_flight", factory=_create_post_flight_gate)
moderation_gate_registry.register(backend="composite", factory=_create_composite_gate)


def create_moderation_rule(rule_type: str, **rule_options: Any) -> ModerationRule:
    """Create a moderation rule from a registered rule backend."""
    return moderation_rule_registry.create(backend=rule_type, **rule_options)


def create_moderation_gate(gate_type: str, **gate_options: Any) -> ModerationGate:
    """Create a moderation gate from a registered gate backend."""
    return moderation_gate_registry.create(backend=gate_type, **gate_options)


def create_moderation_pipeline(
    enabled: bool = True,
    fail_on_violation: bool = True,
    *,
    pre_flight: PreFlightGate | None = None,
    post_flight: PostFlightGate | None = None,
    event_bus: EventBus | None = None,
    name: str = "moderation_pipeline",
) -> ModerationPipeline:
    """
    Factory for ModerationPipeline with sensible defaults.

    Args:
        enabled: Enable moderation checks (not used, kept for API compatibility)
        fail_on_violation: Fail requests on violations (not used, kept for API compatibility)

    Returns:
        Configured ModerationPipeline instance

    Example:
        # With defaults
        pipeline = create_moderation_pipeline()

        # Warning mode (log but don't fail)
        pipeline = create_moderation_pipeline(fail_on_violation=False)
    """
    # `enabled` / `fail_on_violation` are kept for backward compatibility.
    del enabled, fail_on_violation
    return ModerationPipeline(
        pre_flight=pre_flight,
        post_flight=post_flight,
        event_bus=event_bus,
        name=name,
    )


def create_keyword_rule(
    *,
    blocked_words: tuple[str, ...] = (),
    whole_word_only: bool = True,
    severity: ModerationSeverity = "error",
) -> KeywordRule:
    """Create a KeywordRule with explicit blocked-word settings."""
    rule = create_moderation_rule(
        "keyword",
        blocked_words=blocked_words,
        whole_word_only=whole_word_only,
        severity=severity,
    )
    if not isinstance(rule, KeywordRule):
        raise TypeError("keyword rule backend must return KeywordRule for create_keyword_rule().")
    return rule


def create_post_flight_gate(
    *,
    rules: list[ModerationRule] | None = None,
    redact_on_violation: bool = False,
    name: str = "post_flight",
) -> PostFlightGate:
    """Create a PostFlightGate with explicit rule wiring."""
    gate = create_moderation_gate(
        "post_flight",
        rules=rules or [],
        redact_on_violation=redact_on_violation,
        name=name,
    )
    if not isinstance(gate, PostFlightGate):
        raise TypeError("post_flight gate backend must return PostFlightGate for create_post_flight_gate().")
    return gate


def create_keyword_moderation_pipeline(
    *,
    blocked_words: tuple[str, ...] = (),
    whole_word_only: bool = True,
    severity: ModerationSeverity = "error",
    redact_on_violation: bool = False,
    event_bus: EventBus | None = None,
    gate_name: str = "post_flight",
    pipeline_name: str = "moderation_pipeline",
) -> ModerationPipeline:
    """Create a moderation pipeline backed by a single keyword-based post-flight gate."""
    post_flight = create_post_flight_gate(
        rules=[
            create_keyword_rule(
                blocked_words=blocked_words,
                whole_word_only=whole_word_only,
                severity=severity,
            )
        ],
        redact_on_violation=redact_on_violation,
        name=gate_name,
    )
    return create_moderation_pipeline(
        post_flight=post_flight,
        event_bus=event_bus,
        name=pipeline_name,
    )


def create_moderation_pipeline_from_config(settings: Settings | None = None) -> ModerationPipeline:
    """
    Create ModerationPipeline from environment configuration.

    Reads from environment variables:
    - CEMAF_MODERATION_ENABLED: Enable moderation (default: True)
    - CEMAF_MODERATION_FAIL_ON_VIOLATION: Fail on violations (default: True)

    Returns:
        Configured ModerationPipeline instance

    Example:
        # From environment
        pipeline = create_moderation_pipeline_from_config()
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    enabled = os.getenv("CEMAF_MODERATION_ENABLED", "true").lower() == "true"
    fail_on_violation = os.getenv("CEMAF_MODERATION_FAIL_ON_VIOLATION", "true").lower() == "true"

    return create_moderation_pipeline(
        enabled=enabled,
        fail_on_violation=fail_on_violation,
    )
