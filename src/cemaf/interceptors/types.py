"""Decision types for the interceptor spine (SPEC-01a §2 + RECOVER extension).

Names align with the full SPEC-01 (`PreflightDecision`/`PostflightDecision`, one
`DecisionKind` superset) so the richer spec extends rather than renames.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from cemaf.agents.base import AgentContext
from cemaf.core.types import JSON

# Hint length policy — module-level so callers can subclass / use sentinel values
# in tests instead of magic numbers. These are *invariants of the type* (a hint
# the LLM can't realistically read isn't useful), so they live here, not in
# CouncilConfig-style runtime config. Adjust at the source if the contract changes.
MAX_HINT_DETAIL_CHARS: Final[int] = 1024
MAX_HINT_ACTION_CHARS: Final[int] = 512

# Namespaced keys CEMAF writes into AgentContext.global_memory. The dunder
# wrapping signals "framework-owned, do not squat" to library consumers.
RECOVERY_HINTS_KEY: Final[str] = "__cemaf_recovery_hints__"
COUNCIL_PRIOR_ROUND_KEY: Final[str] = "__cemaf_council_prior_round__"

# Cap on hints visible to the agent on any single attempt — keeps token cost
# bounded as the loop iterates and ensures the LATEST hints (the most actionable
# feedback) win when the budget is large.
MAX_VISIBLE_HINTS: Final[int] = 3


class DecisionKind(StrEnum):
    ACCEPT = "accept"  # proceed (PRE: run agent / POST: keep result)
    REJECT = "reject"  # short-circuit (PRE: skip agent / POST: fail the node)
    RECOVER = "recover"  # POST only: re-run the agent with a feedback hint (bounded)
    # HALT is added by full SPEC-01; this slice handles ACCEPT/REJECT/RECOVER.


@dataclass(frozen=True, slots=True)
class RecoveryHint:
    """Feedback an interceptor injects when it asks the executor to re-run the node.

    The executor surfaces hints under ``agent_context.global_memory[RECOVERY_HINTS_KEY]``
    on the next attempt — the agent sees prior failures and can correct. Bounded by
    the executor's per-node ``max_recovery_attempts`` cap (deterministic gates can't
    loop forever).
    """

    interceptor_id: str
    code: str  # short machine tag, e.g. "length", "schema", "ungrounded_claim"
    detail: str  # human-readable; SHALL be ≤ 1024 chars
    suggested_action: str = ""  # optional; ≤ 512 chars

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("RecoveryHint.code must be non-empty")
        if not self.detail.strip():
            raise ValueError("RecoveryHint.detail must be non-empty")
        if len(self.detail) > MAX_HINT_DETAIL_CHARS:
            raise ValueError(
                f"RecoveryHint.detail exceeds {MAX_HINT_DETAIL_CHARS} chars (got {len(self.detail)})"
            )
        if len(self.suggested_action) > MAX_HINT_ACTION_CHARS:
            raise ValueError(
                f"RecoveryHint.suggested_action exceeds {MAX_HINT_ACTION_CHARS} chars "
                f"(got {len(self.suggested_action)})"
            )

    def to_dict(self) -> JSON:
        return {
            "interceptor_id": self.interceptor_id,
            "code": self.code,
            "detail": self.detail,
            "suggested_action": self.suggested_action,
        }


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    """Outcome of one PRE interceptor.

    On ACCEPT, `enriched_context` (if set) replaces the context seen by the next
    interceptor and the agent — built via `AgentContext.model_copy(update=...)`.
    None means "use prior context unchanged".
    """

    kind: DecisionKind
    interceptor_id: str
    enriched_context: AgentContext | None = None
    reason: str | None = None  # required (non-empty) when REJECT

    def __post_init__(self) -> None:
        if self.kind is DecisionKind.RECOVER:
            raise ValueError("PRE interceptors cannot RECOVER; use ACCEPT-with-enrichment or REJECT")
        if self.kind is DecisionKind.REJECT and not (self.reason and self.reason.strip()):
            raise ValueError("PreflightDecision REJECT requires a non-empty reason")


@dataclass(frozen=True, slots=True)
class PostflightDecision:
    """Outcome of one POST interceptor.

    On ACCEPT, `metadata` (if set) is merged under
    `NodeResult.metadata["interceptors"][interceptor_id]` for provenance.
    On RECOVER, `recovery_hint` MUST be set; the executor re-runs the node with
    the hint surfaced in ``agent_context.global_memory[RECOVERY_HINTS_KEY]``,
    bounded by ``max_recovery_attempts``.
    """

    kind: DecisionKind
    interceptor_id: str
    reason: str | None = None  # required (non-empty) when REJECT or RECOVER
    metadata: JSON | None = None
    recovery_hint: RecoveryHint | None = None  # required when RECOVER

    def __post_init__(self) -> None:
        if self.kind is DecisionKind.REJECT and not (self.reason and self.reason.strip()):
            raise ValueError("PostflightDecision REJECT requires a non-empty reason")
        if self.kind is DecisionKind.RECOVER:
            if not (self.reason and self.reason.strip()):
                raise ValueError("PostflightDecision RECOVER requires a non-empty reason")
            if self.recovery_hint is None:
                raise ValueError("PostflightDecision RECOVER requires a recovery_hint")
