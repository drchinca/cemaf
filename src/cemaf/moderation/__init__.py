"""
Moderation module for content safety and compliance.

Provides rules, gates, and utilities for content moderation.
"""

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
    "ModerationGate",
    "ModerationResult",
    "ModerationRule",
    "ModerationSeverity",
    "ModerationViolation",
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
