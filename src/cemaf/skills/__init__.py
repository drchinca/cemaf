"""
Skills module - Composable capabilities using tools.

Skills are the MIDDLE level of the hierarchy:
- COMPOSABLE: Combine multiple tools into a capability
- STATEFUL: Can access context/memory (read-only)
- REUSABLE: Same skill used by different agents
- VALIDATED: Input/output validation with Pydantic

Skills are used BY Agents, and USE Tools.

Example skills:
- DataFetchSkill: Uses http_request + parse_json tools
- SQLAnalysisSkill: Uses sql_query + format_table tools
- ContentGenerationSkill: Uses llm_call + validate_output tools
"""

from cemaf.skills.base import Skill, SkillResult, SkillOutput, SkillContext

__all__ = [
    "Skill",
    "SkillResult",
    "SkillOutput",
    "SkillContext",
]

