"""Goal/result models for blueprint-triad meta-agents (selector + harvester).

Kept in a dedicated module so `meta/goals.py` stays organized around the
original self-hosting agents. Used by `BlueprintSelectorAgent` (PR-2)
and `MetaBlueprintHarvester` (PR-3).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SelectionGoal(BaseModel):
    """Query parameters for `BlueprintSelectorAgent`."""

    model_config = {"frozen": True}

    query: str = Field(min_length=1, description="Goal-describing text to search for")
    k: int = Field(default=1, ge=1, description="How many candidates to consider (returns top 1)")
    tags: tuple[str, ...] = Field(default=(), description="Required tags (at least one must match)")


class SelectionResult(BaseModel):
    """Result from `BlueprintSelectorAgent`."""

    model_config = {"frozen": True}

    entry_id: str | None = Field(default=None, description="Id of the selected BlueprintEntry, if any")
    prompt: str = Field(default="", description="Rendered blueprint.to_prompt() output, or ''")
    score: float = Field(default=0.0, description="Selection score from library.search")


class HarvestGoal(BaseModel):
    """Inputs for `MetaBlueprintHarvester._derive_entry` (exposed for testability)."""

    model_config = {"frozen": True}

    run_id: str
    node_id: str
    overall_score: float = Field(ge=0.0, le=1.0)
    goal_text: str
    output_text: str
    tags: tuple[str, ...] = ()


class HarvestResult(BaseModel):
    """Outcome of a harvest attempt — emitted primarily for telemetry/tests."""

    model_config = {"frozen": True}

    entry_id: str | None = None
    appended: bool = False
    reason: str = ""


__all__ = [
    "HarvestGoal",
    "HarvestResult",
    "SelectionGoal",
    "SelectionResult",
]
