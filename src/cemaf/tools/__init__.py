"""
Tools module - Atomic, stateless functions.

Tools are the LOWEST level of the hierarchy:
- ATOMIC: Do ONE thing only
- STATELESS: No memory, no side effects beyond their purpose  
- SCHEMA-DRIVEN: Have JSON Schema for LLM function calling
- DETERMINISTIC: Same input → same output (when possible)

Tools are used BY Skills, never directly by Agents.
"""

from cemaf.tools.base import Tool, ToolSchema, ToolResult, tool_decorator

__all__ = [
    "Tool",
    "ToolSchema", 
    "ToolResult",
    "tool_decorator",
]

