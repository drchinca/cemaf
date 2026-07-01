"""
Agents module - Autonomous entities with goals and memory.

Agents are the HIGHEST level of the execution hierarchy:
- AUTONOMOUS: Make decisions about which skills to use
- GOAL-ORIENTED: Work toward completing objectives
- MEMORY-ENABLED: Maintain state across interactions
- CONTEXT-AWARE: Have isolated context scope

Agents USE Skills (which USE Tools).

## Configuration

Settings for this module are defined in AgentsSettings.

Environment Variables:
    CEMAF_AGENTS_MAX_ITERATIONS: Max agent iterations (default: 10)
    CEMAF_AGENTS_MAX_SKILL_CALLS: Max skill calls per agent (default: 50)
    CEMAF_AGENTS_TIMEOUT_SECONDS: Agent timeout in seconds (default: 300.0)
    CEMAF_AGENTS_DEEP_AGENT_MAX_DEPTH: Max depth for DeepAgent (default: 5)
    CEMAF_AGENTS_DEEP_AGENT_MAX_CHILDREN: Max children per node (default: 10)
    CEMAF_AGENTS_DEEP_AGENT_MAX_TOTAL: Max total agents (default: 100)
    CEMAF_AGENTS_DEEP_AGENT_TIMEOUT_SECONDS: DeepAgent timeout (default: 600.0)

## Usage

Protocol-based (Recommended):
    >>> from cemaf.agents import Agent, AgentContext, AgentResult, AgentState
    >>> from cemaf.core.types import AgentID
    >>>
    >>> class MyAgent:
    ...     @property
    ...     def id(self) -> AgentID:
    ...         return AgentID("my_agent")
    ...
    ...     @property
    ...     def description(self) -> str:
    ...         return "My custom agent"
    ...
    ...     @property
    ...     def skills(self) -> tuple:
    ...         return ()
    ...
    ...     async def run(self, goal, context: AgentContext) -> AgentResult:
    ...         return AgentResult.ok("result", AgentState())

## Extension

Agent implementations are protocol-first. Pass any object satisfying the Agent
protocol directly via AgentRegistry.register_agent(...), or register a named
constructor with agent_factory_registry when agents should be created from
dependencies/configuration.

See cemaf.agents.protocols.Agent for the protocol definition.
"""

# Context Engineering Agents
from cemaf.agents.context_agents import (
    LibrarianAgent,
    LibrarianGoal,
    LibrarianResult,
    ResearcherAgent,
    ResearcherGoal,
    ResearcherResult,
    SummarizerAgent,
    SummarizerGoal,
    SummarizerResult,
    WriterAgent,
    WriterGoal,
    WriterResult,
)
from cemaf.agents.factories import create_agent_context, create_agent_context_from_config
from cemaf.agents.protocols import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry, agent_factory_registry, create_default_registry
from cemaf.core.domain import DomainContext

__all__ = [
    # Core protocols
    "Agent",
    "AgentState",
    "AgentResult",
    "AgentContext",
    "DomainContext",
    # Context Engineering Agents
    "LibrarianAgent",
    "LibrarianGoal",
    "LibrarianResult",
    "ResearcherAgent",
    "ResearcherGoal",
    "ResearcherResult",
    "SummarizerAgent",
    "SummarizerGoal",
    "SummarizerResult",
    "WriterAgent",
    "WriterGoal",
    "WriterResult",
    # Registry
    "AgentRegistry",
    "agent_factory_registry",
    "create_default_registry",
    # Factories
    "create_agent_context",
    "create_agent_context_from_config",
]
