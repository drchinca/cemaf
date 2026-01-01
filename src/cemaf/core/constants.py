"""
Framework constants.

All magic numbers and default values live here.
NO HARDCODED VALUES anywhere else in the codebase.

Usage:
    from cemaf.core.constants import DEFAULT_MAX_RETRIES

    class MyConfig(BaseModel):
        max_retries: int = DEFAULT_MAX_RETRIES
"""

from typing import Final

# =============================================================================
# Execution defaults
# =============================================================================
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_RETRY_DELAY_SECONDS: Final[float] = 1.0

# =============================================================================
# Agent defaults
# =============================================================================
DEFAULT_AGENT_MAX_ITERATIONS: Final[int] = 10
DEFAULT_AGENT_MAX_SKILL_CALLS: Final[int] = 50
DEFAULT_AGENT_TIMEOUT_SECONDS: Final[float] = 300.0

# =============================================================================
# DeepAgent defaults
# =============================================================================
DEFAULT_DEEP_AGENT_MAX_DEPTH: Final[int] = 5
DEFAULT_DEEP_AGENT_MAX_CHILDREN: Final[int] = 10
DEFAULT_DEEP_AGENT_MAX_TOTAL: Final[int] = 100
DEFAULT_DEEP_AGENT_TIMEOUT_SECONDS: Final[float] = 600.0

# =============================================================================
# Context/Token limits
# =============================================================================
MAX_CONTEXT_TOKENS: Final[int] = 128_000
DEFAULT_CONTEXT_BUDGET: Final[int] = 8_000
RESERVED_OUTPUT_TOKENS: Final[int] = 4_000
SUMMARIZATION_PROMPT_TEMPLATE: Final[str] = (
    "Summarize the following text to approximately {target_summary_tokens} tokens, "
    "focusing on key facts and essential details:\n\n{text}"
)

# =============================================================================
# Memory defaults
# =============================================================================
DEFAULT_MEMORY_TTL_SECONDS: Final[int] = 3600  # 1 hour for session memory
LONG_TERM_MEMORY_RETENTION_DAYS: Final[int] = 365

# =============================================================================
# Confidence thresholds
# =============================================================================
MIN_CONFIDENCE_THRESHOLD: Final[float] = 0.5
HIGH_CONFIDENCE_THRESHOLD: Final[float] = 0.8

# =============================================================================
# DAG execution
# =============================================================================
MAX_PARALLEL_NODES: Final[int] = 10
MAX_DAG_DEPTH: Final[int] = 50
CYCLE_DETECTION_LIMIT: Final[int] = 1000
DEFAULT_CHECKPOINT_INTERVAL: Final[int] = 1
