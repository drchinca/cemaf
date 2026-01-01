"""
CEMAF - Context Engineering Multi-Agent Framework

A pluggable, modular framework for building AI agent systems with:
- Tools: Atomic, stateless functions
- Skills: Composable capabilities using tools
- Agents: Autonomous entities with goals and memory
- DeepAgent: Hierarchical orchestration with context isolation
- Dynamic DAGs: Runtime workflow composition

Author: Hikuri Bado Chinca (@drchinca)
Email: chincadr@gmail.com
"""

__version__ = "0.1.0"

from cemaf.core.enums import AgentStatus, MemoryScope, NodeType, RunStatus
from cemaf.core.types import JSON, AgentID, NodeID, RunID, SkillID, ToolID

__all__ = [
    "__version__",
    # Types
    "JSON",
    "AgentID",
    "NodeID",
    "RunID",
    "SkillID",
    "ToolID",
    # Enums
    "AgentStatus",
    "MemoryScope",
    "NodeType",
    "RunStatus",
]
