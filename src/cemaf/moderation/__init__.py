"""
Moderation module for content safety and compliance.

Provides rules, gates, and utilities for content moderation.
"""

from cemaf.moderation.factories import (
    create_keyword_moderation_pipeline,
    create_keyword_rule,
    create_moderation_pipeline,
    create_post_flight_gate,
)
from cemaf.moderation.gates import (
    CompositeGate,
    PostFlightGate,
    PreFlightGate,
)
from cemaf.moderation.mock import (
    AlwaysBlockGate,
    AlwaysBlockRule,
    AlwaysPassGate,
    AlwaysPassRule,
    MockModerationPipeline,
    RecordingGate,
    RecordingRule,
)
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.moderation.protocols import (
    ModerationContent,
    ModerationGate,
    ModerationResult,
    ModerationRule,
    ModerationSeverity,
    ModerationViolation,
)
from cemaf.moderation.rules import (
    KeywordRule,
    LengthRule,
    PatternRule,
    PIIRule,
)

__all__ = [
    # Protocols and types
    "ModerationContent",
    "ModerationGate",
    "ModerationResult",
    "ModerationRule",
    "ModerationSeverity",
    "ModerationViolation",
    # Factories
    "create_keyword_moderation_pipeline",
    "create_keyword_rule",
    "create_moderation_pipeline",
    "create_post_flight_gate",
    # Gates
    "CompositeGate",
    "PostFlightGate",
    "PreFlightGate",
    # Pipeline
    "ModerationPipeline",
    # Rules
    "KeywordRule",
    "LengthRule",
    "PatternRule",
    "PIIRule",
    # Mocks for testing
    "AlwaysBlockGate",
    "AlwaysBlockRule",
    "AlwaysPassGate",
    "AlwaysPassRule",
    "MockModerationPipeline",
    "RecordingGate",
    "RecordingRule",
]
