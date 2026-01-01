"""
Agent protocols - Abstract interfaces for autonomous agents.

Supports:
- Goal-oriented execution
- Skill composition
- State management
- Iterative reasoning

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Custom agent implementations should implement these protocols rather than
    inheriting from ABC classes. This allows maximum flexibility and follows
    CEMAF's dependency injection principles.

Example:
    >>> from cemaf.agents.protocols import Agent
    >>> from cemaf.core.types import AgentID
    >>>
    >>> class MyCustomAgent:
    ...     @property
    ...     def id(self) -> AgentID:
    ...         return AgentID("my_agent")
    ...
    ...     @property
    ...     def description(self) -> str:
    ...         return "My custom agent"
    ...
    ...     @property
    ...     def skills(self) -> tuple[Any, ...]:
    ...         return ()
    ...
    ...     async def run(self, goal: Any, context: AgentContext) -> AgentResult:
    ...         return AgentResult.ok("result", AgentState())
    >>>
    >>> # No inheritance needed - structural compatibility!
    >>> assert isinstance(MyCustomAgent(), Agent)
"""

from typing import Any, Protocol, runtime_checkable

# Re-export data classes from base (these are not changed)
from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.core.types import AgentID

__all__ = [
    "Agent",
    "AgentContext",
    "AgentResult",
    "AgentState",
]


@runtime_checkable
class Agent[GoalT, ResultT](Protocol):
    """
    Protocol for agent implementations.

    An Agent is an autonomous entity that:
    - Has a unique identifier
    - Has a clear purpose/description
    - Composes skills to accomplish goals
    - Maintains state during execution
    - Returns structured results

    This is a protocol, not an ABC. Any class with these methods is compatible.

    Type Parameters:
        GoalT: Type of goal this agent accepts (typically a Pydantic model)
        ResultT: Type of result this agent produces

    Extension Point:
        Implement this protocol for custom agents:
        - ReAct agents (reasoning + acting)
        - Planning agents (goal decomposition)
        - Conversational agents (dialogue management)
        - Domain-specific agents (SQL, code analysis, etc.)

    Example:
        >>> class AnalystAgent:
        ...     def __init__(self, sql_skill):
        ...         self._sql_skill = sql_skill
        ...
        ...     @property
        ...     def id(self) -> AgentID:
        ...         return AgentID("analyst")
        ...
        ...     @property
        ...     def description(self) -> str:
        ...         return "Analyzes data using SQL queries"
        ...
        ...     @property
        ...     def skills(self) -> tuple[Skill, ...]:
        ...         return (self._sql_skill,)
        ...
        ...     async def run(self, goal: AnalysisGoal, ctx: AgentContext) -> AgentResult[AnalysisResult]:
        ...         state = AgentState()
        ...         result = await self._sql_skill.execute(goal.query, ctx)
        ...         if not result.success:
        ...             return AgentResult.fail(result.error, state)
        ...         return AgentResult.ok(AnalysisResult(data=result.output), state)
        >>>
        >>> # Automatically compatible - no inheritance!
        >>> agent = AnalystAgent(sql_skill)
        >>> assert isinstance(agent, Agent)

    Best Practices:
        1. **Dependency Injection**: Accept all dependencies in __init__
        2. **Immutable State**: Return new AgentState, never mutate
        3. **Result Pattern**: Always return AgentResult[T], never raise
        4. **Skill Composition**: Use skills for reusable capabilities
        5. **Context Isolation**: Each agent has isolated AgentContext

    See Also:
        - cemaf.agents.base.Agent (deprecated ABC, use this protocol instead)
        - cemaf.skills.protocols.Skill (skill protocol)
        - cemaf.orchestration.deep_agent.DeepAgent (hierarchical agent orchestration)
    """

    @property
    def id(self) -> AgentID:
        """
        Unique identifier for this agent.

        Returns:
            AgentID instance (typically AgentID("name"))

        Example:
            >>> @property
            >>> def id(self) -> AgentID:
            ...     return AgentID("my_agent")
        """
        ...

    @property
    def description(self) -> str:
        """
        Human-readable description of what this agent does.

        Returns:
            Clear, concise description of agent's purpose

        Example:
            >>> @property
            >>> def description(self) -> str:
            ...     return "Analyzes data and generates reports"
        """
        ...

    @property
    def skills(self) -> tuple[Any, ...]:
        """
        Skills available to this agent.

        Skills are composable capabilities that agents use to accomplish goals.
        This tuple defines which skills this agent has access to.

        Returns:
            Tuple of Skill instances (empty tuple if no skills)

        Example:
            >>> @property
            >>> def skills(self) -> tuple[Skill, ...]:
            ...     return (self._sql_skill, self._analysis_skill)
        """
        ...

    async def run(self, goal: GoalT, context: AgentContext) -> AgentResult[ResultT]:
        """
        Execute the agent to accomplish a goal.

        This is the main entry point for agent execution. The agent should:
        1. Validate the goal
        2. Plan approach (if needed)
        3. Execute skills to accomplish goal
        4. Track state throughout execution
        5. Return structured result

        Args:
            goal: Goal to accomplish (typically a Pydantic model)
            context: Execution context with run metadata, parent info, memory

        Returns:
            AgentResult containing:
            - success: Whether goal was accomplished
            - output: The result data (if successful)
            - error: Error message (if failed)
            - final_state: Final agent state
            - skill_results: Trace of skill executions
            - metadata: Additional execution metadata

        Example:
            >>> async def run(self, goal: AnalysisGoal, context: AgentContext) -> AgentResult[AnalysisResult]:
            ...     state = AgentState()
            ...
            ...     # Execute skills
            ...     result = await self._sql_skill.execute(goal.query, context)
            ...     state = state.next(skill_calls=1)
            ...
            ...     if not result.success:
            ...         return AgentResult.fail(result.error, state)
            ...
            ...     # Process results
            ...     analysis = self._analyze_data(result.output)
            ...     state = state.next(status=AgentStatus.COMPLETED)
            ...
            ...     return AgentResult.ok(AnalysisResult(data=analysis), state)

        Best Practices:
            - Always return AgentResult, never raise exceptions
            - Track iterations and skill calls in state
            - Include metadata for debugging/observability
            - Use context patches to share data with downstream nodes
            - Check cancellation tokens if long-running
        """
        ...
