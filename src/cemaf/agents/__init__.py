"""
Agents module - Autonomous entities with goals and memory.

Agents are the HIGHEST level of the execution hierarchy:
- AUTONOMOUS: Make decisions about which skills to use
- GOAL-ORIENTED: Work toward completing objectives
- MEMORY-ENABLED: Maintain state across interactions
- CONTEXT-AWARE: Have isolated context scope

Agents USE Skills (which USE Tools).

Agent types:
- BaseAgent: Single-purpose agent
- DeepAgent: Can spawn child agents with isolated context
"""

from cemaf.agents.base import Agent, AgentState, AgentResult, AgentContext

__all__ = [
    "Agent",
    "AgentState",
    "AgentResult",
    "AgentContext",
]

