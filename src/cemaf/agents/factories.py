"""
Factory functions for agent components.

Provides convenient ways to create agent contexts and configurations
with sensible defaults while maintaining dependency injection principles.

Note:
    Agents are protocol-based abstractions that users implement.
    This module provides factory functions for agent contexts and configurations,
    not for agent instances themselves.

Extension Point:
    This module is designed for extension. Add your custom agent
    implementations and register them here if needed.
"""

import os

from cemaf.agents.protocols import AgentContext
from cemaf.config.protocols import Settings
from cemaf.context.context import Context
from cemaf.core.types import AgentID


def create_agent_context(
    agent_id: AgentID,
    context: Context | None = None,
    max_iterations: int = 10,
    max_skill_calls: int = 50,
    timeout_seconds: float = 300.0,
) -> AgentContext:
    """
    Factory for AgentContext with sensible defaults.

    Args:
        agent_id: Unique agent identifier
        context: Base context (creates new if None)
        max_iterations: Maximum agent iterations
        max_skill_calls: Maximum skill calls per agent
        timeout_seconds: Agent execution timeout

    Returns:
        Configured AgentContext instance

    Example:
        # Basic agent context
        from cemaf.core.types import AgentID
        agent_ctx = create_agent_context(AgentID("my_agent"))

        # With custom limits
        agent_ctx = create_agent_context(
            AgentID("my_agent"),
            max_iterations=20,
            timeout_seconds=600.0
        )
    """
    base_context = context or Context.empty()

    return AgentContext(
        agent_id=agent_id,
        context=base_context,
        max_iterations=max_iterations,
        max_skill_calls=max_skill_calls,
        timeout_seconds=timeout_seconds,
    )


def create_agent_context_from_config(
    agent_id: AgentID,
    context: Context | None = None,
    settings: Settings | None = None,
) -> AgentContext:
    """
    Create AgentContext from environment configuration.

    Reads from environment variables:
    - CEMAF_AGENTS_MAX_ITERATIONS: Max iterations (default: 10)
    - CEMAF_AGENTS_MAX_SKILL_CALLS: Max skill calls (default: 50)
    - CEMAF_AGENTS_TIMEOUT_SECONDS: Timeout in seconds (default: 300.0)

    Args:
        agent_id: Unique agent identifier
        context: Base context (creates new if None)

    Returns:
        Configured AgentContext instance

    Example:
        # From environment
        from cemaf.core.types import AgentID
        agent_ctx = create_agent_context_from_config(AgentID("my_agent"))
    """
    max_iterations = int(os.getenv("CEMAF_AGENTS_MAX_ITERATIONS", "10"))
    max_skill_calls = int(os.getenv("CEMAF_AGENTS_MAX_SKILL_CALLS", "50"))
    timeout_seconds = float(os.getenv("CEMAF_AGENTS_TIMEOUT_SECONDS", "300.0"))

    return create_agent_context(
        agent_id=agent_id,
        context=context,
        max_iterations=max_iterations,
        max_skill_calls=max_skill_calls,
        timeout_seconds=timeout_seconds,
    )


# ============================================================================
# EXTEND HERE: Bring Your Own Agent Implementations
# ============================================================================
# This is the extension point for custom agent implementations.
#
# To add your own agent type:
# 1. Implement the Agent protocol (see cemaf.agents.protocols)
# 2. Add a factory function below
# 3. Optionally add a config-based factory
#
# Example (ReAct Agent):
#   def create_react_agent(
#       agent_id: AgentID,
#       llm: LLMClient,
#       skills: tuple[Skill, ...],
#   ) -> Agent:
#       from your_package import ReActAgent
#       return ReActAgent(agent_id=agent_id, llm=llm, skills=skills)
#
#   def create_react_agent_from_config(
#       agent_id: AgentID,
#       skills: tuple[Skill, ...],
#   , settings: Settings | None = None) -> Agent:
#       from cemaf.llm.factories import create_llm_client_from_config
#       llm = create_llm_client_from_config()
#       return create_react_agent(agent_id, llm, skills)
#
# Example (Planning Agent):
#   def create_planning_agent(
#       agent_id: AgentID,
#       llm: LLMClient,
#       planner: Planner,
#   ) -> Agent:
#       from your_package import PlanningAgent
#       return PlanningAgent(agent_id=agent_id, llm=llm, planner=planner)
# ============================================================================
