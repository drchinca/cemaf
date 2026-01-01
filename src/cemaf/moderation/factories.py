"""
Factory functions for moderation components.

Provides convenient ways to create moderation pipelines with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.moderation.pipeline import ModerationPipeline


def create_moderation_pipeline(
    enabled: bool = True,
    fail_on_violation: bool = True,
) -> ModerationPipeline:
    """
    Factory for ModerationPipeline with sensible defaults.

    Args:
        enabled: Enable moderation checks
        fail_on_violation: Fail requests on violations

    Returns:
        Configured ModerationPipeline instance

    Example:
        # With defaults
        pipeline = create_moderation_pipeline()

        # Warning mode (log but don't fail)
        pipeline = create_moderation_pipeline(fail_on_violation=False)
    """
    return ModerationPipeline(
        enabled=enabled,
        fail_on_violation=fail_on_violation,
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
