"""
Core type aliases for the framework.

Using NewType for type safety - these catch bugs at type-check time.
"""

from typing import Any, NewType

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
