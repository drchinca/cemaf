"""Experimental context-backed state object for agent prompts."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.context.context import Context
from cemaf.core.experimental import experimental


@runtime_checkable
class MindStateComponent(Protocol):
    """Protocol for components that can be part of a MindState."""

    def apply_to_context(self, context: Context) -> Context:
        """Apply this component's logic to a context."""
        ...


@experimental
class MindState(BaseModel):
    """
    Experimental context-backed state object for agent prompts.

    STABILITY: Unstable - API subject to change without notice.
    This class is experimental and not recommended for production use. The
    current implementation stores a Context, applies components in order, and
    renders context data into a prompt.
    """

    model_config = {"frozen": True}

    id: str = Field(description="Unique identifier for this mind state")
    context: Context = Field(default_factory=Context, description="The current cognitive context")

    @classmethod
    def build(cls, components: list[MindStateComponent]) -> MindState:
        """
        Declaratively build a MindState from a list of components.

        Example:
            state = MindState.build([])
        """
        import uuid

        ctx = Context()
        for component in components:
            ctx = component.apply_to_context(ctx)

        return cls(id=str(uuid.uuid4()), context=ctx)

    def to_prompt(self) -> str:
        """Convert MindState into a structured prompt for an LLM."""
        if not self.context.data:
            return f"[MindState:{self.id}] Empty context"
        parts: list[str] = []
        for key, value in self.context.data.items():
            parts.append(f"[{key}]\n{value}")
        return "\n\n".join(parts)
