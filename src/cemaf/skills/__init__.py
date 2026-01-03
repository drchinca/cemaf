"""
Skills module - Composable capabilities using tools.

Skills are the MIDDLE level of the hierarchy:
- COMPOSABLE: Combine multiple tools into a capability
- STATEFUL: Can access context/memory (read-only)
- REUSABLE: Same skill used by different agents
- VALIDATED: Input/output validation with Pydantic

Skills are used BY Agents, and USE Tools.

## Configuration

Settings for this module are defined in ToolsSettings (skills and tools share settings).

Environment Variables:
    CEMAF_TOOLS_ENABLE_CALL_RECORDING: Record all tool calls (default: True)
    CEMAF_TOOLS_MAX_TOOL_TIMEOUT_SECONDS: Max timeout for tools (default: 60.0)
    CEMAF_TOOLS_ENABLE_MODERATION: Enable content moderation (default: False)
    CEMAF_TOOLS_ENABLE_CACHING: Enable result caching (default: True)

## Usage

Protocol-based:
    >>> from cemaf.skills import Skill, SkillContext, SkillOutput, SkillResult
    >>> from cemaf.core.types import SkillID
    >>> from cemaf.core.result import Result
    >>>
    >>> class MySkill:
    ...     @property
    ...     def id(self) -> SkillID:
    ...         return SkillID("my_skill")
    ...
    ...     @property
    ...     def description(self) -> str:
    ...         return "My custom skill"
    ...
    ...     @property
    ...     def tools(self) -> tuple:
    ...         return ()
    ...
    ...     async def execute(self, input, context: SkillContext) -> SkillResult:
    ...         return Result.ok(SkillOutput(data="result"))

## Extension

Skill implementations are discovered via protocols. No registration needed.
Simply implement the Skill protocol and your skill is compatible with all
CEMAF orchestration systems.

See cemaf.skills.protocols.Skill for the protocol definition.
"""

from cemaf.skills.protocols import Skill, SkillContext, SkillOutput, SkillResult
from cemaf.skills.registry import RegistryError, SkillRegistry

__all__ = [
    "Skill",
    "SkillResult",
    "SkillOutput",
    "SkillContext",
    # Registry (new in Phase 1 Week 2)
    "SkillRegistry",
    "RegistryError",
]
