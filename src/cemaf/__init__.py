"""
CEMAF - Context Engineering Multi-Agent Framework

Quickstart:
    from cemaf import create_executor, AgentRegistry, DAG, Context

    registry = AgentRegistry()
    executor = create_executor(agent_registry=registry)
    result = await executor.run(dag=my_dag)
"""

from importlib.metadata import version as _get_version

__version__ = _get_version("cemaf")

# Core types and enums
# Key protocols
from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry

# Entry points
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import ContextCompiler, PriorityContextCompiler
from cemaf.context.context import Context
from cemaf.context.source import ContextSource
from cemaf.core.enums import AgentStatus, MemoryScope, NodeType, RunStatus, ToolRiskLevel
from cemaf.core.result import Result
from cemaf.core.types import JSON, AgentID, NodeID, RunID, SkillID, ToolID
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor
from cemaf.orchestration.services import RuntimeServices
from cemaf.tools.base import Tool, ToolSchema, tool
from cemaf.tools.registry import ToolRegistry

__all__ = [
    "__version__",
    # Entry points
    "create_executor",
    # Core types
    "JSON",
    "AgentID",
    "NodeID",
    "RunID",
    "SkillID",
    "ToolID",
    "Result",
    # Enums
    "AgentStatus",
    "MemoryScope",
    "NodeType",
    "RunStatus",
    "ToolRiskLevel",
    # Agent system
    "Agent",
    "AgentContext",
    "AgentResult",
    "AgentState",
    "AgentRegistry",
    # Tools
    "Tool",
    "ToolSchema",
    "ToolRegistry",
    "tool",
    # Orchestration
    "DAG",
    "Node",
    "Edge",
    "DAGExecutor",
    "RuntimeServices",
    # Context
    "Context",
    "ContextSource",
    "ContextCompiler",
    "PriorityContextCompiler",
    "TokenBudget",
]
