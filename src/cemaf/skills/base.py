"""
Skill base classes.

A Skill is:
- A composable capability that uses one or more Tools
- Has access to context (read-only)
- Returns Result with output data
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from cemaf.core.types import JSON, SkillID
from cemaf.core.result import Result
from cemaf.tools.base import Tool, ToolResult

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class SkillOutput(Generic[OutputT]):
    """Skill result with tool call trace."""
    
    data: OutputT
    tool_calls: tuple[ToolResult, ...] = ()


# Type alias for skill results
SkillResult = Result[SkillOutput[Any]]


class SkillContext(BaseModel):
    """Read-only context provided to skills."""
    
    model_config = {"frozen": True}
    
    run_id: str
    agent_id: str
    memory: JSON = Field(default_factory=dict)
    artifacts: JSON = Field(default_factory=dict)


class Skill(ABC, Generic[InputT, OutputT]):
    """
    Abstract base class for skills.
    
    Example:
        class DataFetchSkill(Skill[FetchInput, FetchOutput]):
            def __init__(self, http_tool: Tool, parser_tool: Tool):
                self._http = http_tool
                self._parser = parser_tool
            
            @property
            def id(self) -> SkillID:
                return SkillID("data_fetch")
            
            @property
            def tools(self) -> tuple[Tool, ...]:
                return (self._http, self._parser)
            
            async def execute(self, input: FetchInput, ctx: SkillContext) -> SkillResult:
                http_result = await self._http.execute(url=input.url)
                if not http_result.success:
                    return Result.fail(http_result.error or "HTTP failed")
                
                parse_result = await self._parser.execute(data=http_result.data)
                if not parse_result.success:
                    return Result.fail(parse_result.error or "Parse failed")
                
                return Result.ok(SkillOutput(
                    data=FetchOutput(data=parse_result.data),
                    tool_calls=(http_result, parse_result)
                ))
    """
    
    @property
    @abstractmethod
    def id(self) -> SkillID:
        """Unique identifier for this skill."""
        ...
    
    @property
    @abstractmethod
    def description(self) -> str:
        """What this skill does."""
        ...
    
    @property
    @abstractmethod
    def tools(self) -> tuple[Tool, ...]:
        """Tools used by this skill."""
        ...
    
    @abstractmethod
    async def execute(self, input: InputT, context: SkillContext) -> SkillResult:
        """Execute the skill."""
        ...
