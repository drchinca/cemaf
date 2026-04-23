"""Blueprint retrieval — `BlueprintSelectorAgent` + `LibraryBlueprintSelectorHook`.

Two cooperating pieces that let a running DAG consult the `BlueprintLibrary`
for a just-in-time prompt preamble:

1. `BlueprintSelectorAgent` — a standard `Agent[SelectionGoal, SelectionResult]`
   that callers can dispatch as a DAG node (e.g. via `MetaBlueprintSelector` →
   routed goal). Useful when you want blueprint selection as an explicit step
   in a plan.

2. `LibraryBlueprintSelectorHook` — an adapter that wraps the same library
   call behind the minimal `BlueprintSelectorHook` protocol from
   `cemaf.orchestration.blueprint_hook`. Injected into `ContextNodeExecutor`
   so **every** context-compiled node gets a blueprint preamble without any
   DAG changes.

Both read from the same `BlueprintLibrary` and produce identical
results for the same query — pick the one that fits the call site.
Retrieval is purely deterministic (weighted token overlap via
`library.search`) — no LLM call, cheap enough to run per node.
"""

from __future__ import annotations

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.blueprint.library import BlueprintLibrary
from cemaf.core.types import AgentID
from cemaf.meta.blueprint_goals import SelectionGoal, SelectionResult


class BlueprintSelectorAgent(Agent[SelectionGoal, SelectionResult]):
    """Deterministic retrieval over a `BlueprintLibrary` — returns the top match's prompt."""

    def __init__(self, *, library: BlueprintLibrary) -> None:
        self._library = library

    @property
    def id(self) -> AgentID:
        return AgentID("MetaBlueprintSelector")

    @property
    def description(self) -> str:
        return "Retrieves the top blueprint match for a goal query and renders its prompt."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: SelectionGoal,
        context: AgentContext,
    ) -> AgentResult[SelectionResult]:
        state = AgentState()
        hits = self._library.search(query=goal.query, k=goal.k, tags=goal.tags or None)
        if not hits:
            return AgentResult.ok(SelectionResult(), state)

        entry, score = hits[0]
        try:
            blueprint = self._library.resolve(entry_id=entry.id)
        except Exception as exc:
            return AgentResult.fail(
                f"Blueprint {entry.id!r} failed to resolve: {exc}",
                state,
            )

        return AgentResult.ok(
            SelectionResult(
                entry_id=entry.id,
                prompt=blueprint.to_prompt(),
                score=score,
            ),
            state,
        )


class LibraryBlueprintSelectorHook:
    """`BlueprintSelectorHook` impl that wraps a `BlueprintLibrary` directly."""

    def __init__(
        self,
        *,
        library: BlueprintLibrary,
        tags: tuple[str, ...] = (),
    ) -> None:
        self._library = library
        self._tags = tags

    async def select(self, *, query: str) -> str:
        """Return the top match's rendered prompt, or '' on miss/failure."""
        if not query:
            return ""
        hits = self._library.search(query=query, k=1, tags=self._tags or None)
        if not hits:
            return ""
        entry, _score = hits[0]
        try:
            blueprint = self._library.resolve(entry_id=entry.id)
        except Exception:
            # Resolution failures should degrade gracefully — the node still runs
            # without a blueprint preamble rather than breaking the pipeline.
            return ""
        return blueprint.to_prompt()


__all__ = ["BlueprintSelectorAgent", "LibraryBlueprintSelectorHook"]
