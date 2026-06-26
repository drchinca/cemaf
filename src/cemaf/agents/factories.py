"""
Factory functions for agent components.

Provides convenient ways to create agent contexts and configurations
with sensible defaults while maintaining dependency injection principles.

Note:
    Agents are protocol-based abstractions that users implement.
    This module provides factory functions for agent contexts and configurations,
    not for agent instances themselves.

Extension Point:
    Agent implementations are protocol-first. Register constructed agents with
    AgentRegistry.register_agent(...), or register named constructors with
    agent_factory_registry for config/dependency-driven creation.
"""

import os

from cemaf.agents.protocols import AgentContext
from cemaf.config.protocols import Settings
from cemaf.core.types import JSON, AgentID
from cemaf.core.utils import generate_id


def create_agent_context(
    agent_id: AgentID,
    run_id: str | None = None,
    parent_agent_id: str | None = None,
    depth: int = 0,
    global_memory: JSON | None = None,
    artifacts: JSON | None = None,
) -> AgentContext:
    """
    Factory for AgentContext with sensible defaults.

    Args:
        agent_id: Unique agent identifier
        run_id: Run identifier (auto-generated if None)
        parent_agent_id: Parent agent ID for hierarchical agents
        depth: Nesting depth in agent hierarchy
        global_memory: Shared memory across agents
        artifacts: Shared artifacts across agents

    Returns:
        Configured AgentContext instance

    Example:
        # Basic agent context
        from cemaf.core.types import AgentID
        agent_ctx = create_agent_context(AgentID("my_agent"))

        # With parent agent
        agent_ctx = create_agent_context(
            AgentID("child_agent"),
            parent_agent_id="parent_agent",
            depth=1
        )
    """
    return AgentContext(
        run_id=run_id or generate_id("run"),
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        depth=depth,
        global_memory=global_memory or {},
        artifacts=artifacts or {},
    )


def create_agent_context_from_config(
    agent_id: AgentID,
    run_id: str | None = None,
    settings: Settings | None = None,
) -> AgentContext:
    """
    Create AgentContext from environment configuration.

    Reads from environment variables:
    - CEMAF_AGENT_PARENT_ID: Parent agent ID (optional)
    - CEMAF_AGENT_DEPTH: Agent depth in hierarchy (default: 0)

    Args:
        agent_id: Unique agent identifier
        run_id: Run identifier (auto-generated if None)
        settings: Settings provider (unused, kept for backward compatibility)

    Returns:
        Configured AgentContext instance

    Example:
        # From environment
        from cemaf.core.types import AgentID
        agent_ctx = create_agent_context_from_config(AgentID("my_agent"))
    """
    parent_agent_id = os.getenv("CEMAF_AGENT_PARENT_ID")
    depth = int(os.getenv("CEMAF_AGENT_DEPTH", "0"))

    return create_agent_context(
        agent_id=agent_id,
        run_id=run_id,
        parent_agent_id=parent_agent_id,
        depth=depth,
    )
