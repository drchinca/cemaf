"""
Core enums for the framework.

All status enums, type enums, and scope enums live here.
"""

from enum import Enum


class AgentStatus(str, Enum):
    """Status of an agent during execution."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStatus(str, Enum):
    """Status of a pipeline/workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeType(str, Enum):
    """Type of node in a DAG."""

    TOOL = "tool"
    SKILL = "skill"
    AGENT = "agent"
    ROUTER = "router"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"


class MemoryScope(str, Enum):
    """Scope for memory items - from start.ini."""

    BRAND = "brand"
    PROJECT = "project"
    AUDIENCE_SEGMENT = "audience_segment"
    PLATFORM = "platform"
    PERSONAE = "personae"
    SESSION = "session"  # Short-term, single run


class ContextArtifactType(str, Enum):
    """Type of context artifact - from start.ini."""

    BRAND_CONSTITUTION = "brand_constitution"
    BRAND_STYLE_GUIDE = "brand_style_guide"
    SYMBOL_CANON = "symbol_canon"
    CONTENT_ATOMS = "content_atoms"
    CAMPAIGN_BRIEF = "campaign_brief"
    PROMPT_TEMPLATE = "prompt_template"
    DESIGN_TEMPLATE = "design_template"
    GLOSSARY = "glossary"
    DO_NOT_SAY = "do_not_say"


class Priority(str, Enum):
    """Priority levels for task scheduling."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
