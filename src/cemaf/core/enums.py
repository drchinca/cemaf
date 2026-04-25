"""
Core enums for the framework.

All status enums, type enums, and scope enums live here.
"""

from enum import StrEnum


class AgentStatus(StrEnum):
    """Status of an agent during execution."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStatus(StrEnum):
    """Status of a pipeline/workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeType(StrEnum):
    """Type of node in a DAG."""

    TOOL = "tool"
    SKILL = "skill"
    AGENT = "agent"
    ROUTER = "router"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    LOOP = "loop"
    CHECKPOINT = "checkpoint"


class MemoryScope(StrEnum):
    """Scope for memory items - from start.ini."""

    BRAND = "brand"
    PROJECT = "project"
    AUDIENCE_SEGMENT = "audience_segment"
    PLATFORM = "platform"
    PERSONAE = "personae"
    SESSION = "session"  # Short-term, single run
    STRATEGY = "strategy"  # Cross-run learned strategies


class ContextArtifactType(StrEnum):
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


class Priority(StrEnum):
    """Priority levels for task scheduling."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VerificationStatus(StrEnum):
    """Verification state of a cited fact."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    RETRACTED = "retracted"


class ExclusionReason(StrEnum):
    """Reason a context source was excluded from compilation."""

    BUDGET_EXCEEDED = "budget_exceeded"
    LOW_PRIORITY = "low_priority"
    STALE = "stale"
    DUPLICATE = "duplicate"
    FILTERED = "filtered"


class ToolRiskLevel(StrEnum):
    """Risk classification for tool actions — gates execution policy."""

    LOW = "low"  # Read-only, no side effects (e.g., search, introspect)
    MEDIUM = "medium"  # Writes data, reversible (e.g., add entity, update config)
    HIGH = "high"  # Destructive or irreversible (e.g., delete, deploy, send)


class TrustLevel(StrEnum):
    """Trust state for dynamic tools and skills."""

    UNTRUSTED = "untrusted"  # Brand new, not yet verified
    SANDBOXED = "sandboxed"  # Some history, still runs in sandbox
    TRUSTED = "trusted"  # Proven reliable, runs natively
    DEPRECATED = "deprecated"  # Too many failures, no longer used


class MemoryBackend(StrEnum):
    """Backend kind for `create_memory_store` and `MemoryStore` factories."""

    MEMORY = "memory"  # in-process InMemoryStore (tests, dev)
    JSON_FILE = "json_file"  # JsonFileMemoryStore (single-process persistence)
    SQLITE = "sqlite"  # SqliteMemoryStore (durable, single-host)
    POSTGRES = "postgres"  # PostgresMemoryStore (multi-replica, prod)
