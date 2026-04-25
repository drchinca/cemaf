"""`BlueprintSelectorHook` — narrow seam for injecting blueprints into compiled context.

`ContextNodeExecutor` consults this protocol (if configured) right before
compiling the node's context. The hook returns a rendered blueprint
prompt or the empty string. The executor imports only this protocol —
not `BlueprintLibrary`, not `Agent`, not any blueprint type — so the
base framework stays decoupled from the self-hosting layer.

The concrete adapter (`LibraryBlueprintSelectorHook`) lives in
`cemaf.meta.blueprint_selector` where the blueprint dependency is
legitimate. Production wiring injects the adapter via
`RuntimeServices.blueprint_selector`.

When `blueprint_selector=None`, the executor's compile path is
byte-identical to today.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BlueprintSelectorHook(Protocol):
    """Given a goal-describing query, return a rendered blueprint prompt (or empty string)."""

    async def select(self, *, query: str) -> str:
        """Return a prompt preamble to prepend to compiled context, or '' for no match."""
        ...


__all__ = ["BlueprintSelectorHook"]
