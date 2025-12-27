"""
Agent base classes.

An Agent is:
- Autonomous entity with a goal
- Uses skills to accomplish tasks
- Maintains state/memory
- Can make decisions
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from cemaf.core.types import JSON, AgentID
from cemaf.core.enums import AgentStatus
from cemaf.core.utils import utc_now
from cemaf.skills.base import Skill, SkillResult

GoalT = TypeVar("GoalT", bound=BaseModel)
ResultT = TypeVar("ResultT")


class AgentState(BaseModel):
    """Mutable state during agent execution."""
    
    model_config = {"frozen": True}
    
    status: AgentStatus = AgentStatus.IDLE
    iteration: int = 0
    skill_calls: int = 0
    messages: tuple[JSON, ...] = ()
    working_memory: JSON = Field(default_factory=dict)
    
    def next(self, **updates: Any) -> AgentState:
        """Create new state with updates."""
        data = self.model_dump()
        data.update(updates)
        return AgentState(**data)


@dataclass(frozen=True)
class AgentResult(Generic[ResultT]):
    """Result of agent execution with state trace."""
    
    success: bool
    output: ResultT | None = None
    error: str | None = None
    final_state: AgentState | None = None
    skill_results: tuple[SkillResult, ...] = ()
    metadata: JSON = field(default_factory=dict)
    
    @classmethod
    def ok(cls, output: ResultT, state: AgentState) -> AgentResult[ResultT]:
        return cls(success=True, output=output, final_state=state)
    
    @classmethod
    def fail(cls, error: str, state: AgentState | None = None) -> AgentResult[ResultT]:
        return cls(success=False, error=error, final_state=state)


class AgentContext(BaseModel):
    """Isolated context for agent execution."""
    
    model_config = {"frozen": True}
    
    run_id: str
    agent_id: str
    parent_agent_id: str | None = None
    depth: int = 0
    global_memory: JSON = Field(default_factory=dict)
    artifacts: JSON = Field(default_factory=dict)


class Agent(ABC, Generic[GoalT, ResultT]):
    """
    Abstract base class for agents.
    
    Example:
        class AnalystAgent(Agent[AnalysisGoal, AnalysisResult]):
            def __init__(self, sql_skill: Skill):
                self._sql = sql_skill
            
            @property
            def id(self) -> AgentID:
                return AgentID("analyst")
            
            @property
            def skills(self) -> tuple[Skill, ...]:
                return (self._sql,)
            
            async def run(self, goal: AnalysisGoal, ctx: AgentContext) -> AgentResult:
                state = AgentState()
                result = await self._sql.execute(...)
                if not result.success:
                    return AgentResult.fail(result.error, state)
                return AgentResult.ok(AnalysisResult(data=result.data), state)
    """
    
    @property
    @abstractmethod
    def id(self) -> AgentID:
        """Unique identifier."""
        ...
    
    @property
    @abstractmethod
    def description(self) -> str:
        """What this agent does."""
        ...
    
    @property
    @abstractmethod
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        """Skills available to this agent."""
        ...
    
    @abstractmethod
    async def run(self, goal: GoalT, context: AgentContext) -> AgentResult[ResultT]:
        """Execute the agent to accomplish a goal."""
        ...
