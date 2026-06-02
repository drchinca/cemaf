"""
Core type aliases for the framework.

Using NewType for type safety - these catch bugs at type-check time.
"""

from enum import StrEnum
from typing import Any, NewType


class FinishReason(StrEnum):
    """Closed enum classifying how an LLM turn ended (CEMAF v1.0).

    Single source of truth for the normalized finish_reason carried end-to-end
    across adapters, audit, and stream consumers. Adapter implementations
    SHALL map provider-native stop reasons into one of these 5 members.
    """

    TERMINAL_STOP = "stop"
    TERMINAL_TOOL = "tool"
    PARTIAL_LENGTH = "length"
    PARTIAL_FILTER = "filter"
    PARTIAL_ERROR = "error"


class LLMProvider(StrEnum):
    """Closed enum of provider families recognized at the adapter boundary."""

    BEDROCK = "bedrock"
    ANTHROPIC = "anthropic"
    HUGGINGFACE = "huggingface"
    OPENAI = "openai"
    ADAPTER = "adapter"


# JSON-compatible dict type
JSON = dict[str, Any]

# Entity identifiers - NewType for type safety
AgentID = NewType("AgentID", str)
ToolID = NewType("ToolID", str)
SkillID = NewType("SkillID", str)
NodeID = NewType("NodeID", str)
RunID = NewType("RunID", str)
ProjectID = NewType("ProjectID", str)

# Token counts
TokenCount = NewType("TokenCount", int)

# Confidence scores (0.0 - 1.0)
Confidence = NewType("Confidence", float)

# Domain and provenance identifiers
DomainID = NewType("DomainID", str)
TenantID = NewType("TenantID", str)
ProvenanceID = NewType("ProvenanceID", str)

# Trust and strategy identifiers
StrategyID = NewType("StrategyID", str)
TrustScore = NewType("TrustScore", float)
