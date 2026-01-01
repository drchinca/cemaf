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

Agent implementations are discovered via protocols. No registration needed.
Simply implement the Agent protocol and your agent is compatible with all
CEMAF orchestration systems.

See cemaf.agents.protocols.Agent for the protocol definition.
"""

from cemaf.agents.protocols import Agent, AgentContext, AgentResult, AgentState

__all__ = [
    "Agent",
    "AgentState",
    "AgentResult",
    "AgentContext",
]
