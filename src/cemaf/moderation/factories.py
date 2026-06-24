"""
Factory functions for moderation components.

Provides convenient ways to create moderation pipelines with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.events.protocols import EventBus
from cemaf.moderation.gates import PostFlightGate, PreFlightGate
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.moderation.protocols import ModerationRule, ModerationSeverity
from cemaf.moderation.rules import KeywordRule


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
    return KeywordRule(
        blocked_words=blocked_words,
        whole_word_only=whole_word_only,
        severity=severity,
    )


def create_post_flight_gate(
    *,
    rules: list[ModerationRule] | None = None,
    redact_on_violation: bool = False,
    name: str = "post_flight",
) -> PostFlightGate:
    """Create a PostFlightGate with explicit rule wiring."""
    return PostFlightGate(
        rules=rules or [],
        redact_on_violation=redact_on_violation,
        name=name,
    )


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
