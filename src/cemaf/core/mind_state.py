"""
MindState Protocol - The unified declarative schema for agent cognition.
"""

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
    A unified declarative schema for an agent's mental state.
    Combines Context, Memory configuration, and Moderation policies.

    STABILITY: Unstable - API subject to change without notice.
    This class is experimental and not recommended for production use.
    Core functionality (build(), to_prompt()) is incomplete.

    Planned for future implementation:
    - JSX-style builder API
    - Unified prompt generation
    - Memory configuration integration
    - Moderation policy integration
    """

    model_config = {"frozen": True}

    id: str = Field(description="Unique identifier for this mind state")
    context: Context = Field(default_factory=Context, description="The current cognitive context")

    # Placeholders for future unified fields
    # memory_config: MemoryConfig | None = None
    # moderation_policy: ModerationPolicy | None = None

    @classmethod
    def build(cls, components: list[MindStateComponent]) -> MindState:
        """
        Declaratively build a MindState from a list of components.
        This is the foundation for the 'Context JSX' style API.

        Example:
            state = MindState.build([
                MemoryComponent(scope="session"),
                TokenBudgetGate(limit=2000)
            ])
        """
        # TODO: Implement full declarative building logic
        import uuid

        ctx = Context()
        for component in components:
            ctx = component.apply_to_context(ctx)

        return cls(id=str(uuid.uuid4()), context=ctx)

    def to_prompt(self) -> str:
        """
        Convert the entire MindState into a structured prompt for an LLM.
        Unifies blueprints and context.
        """
        # TODO: Implement unified prompt generation
        return ""
