"""
Factory functions for skill components.

Provides convenient ways to create skill wrappers and utilities
with sensible defaults while maintaining dependency injection principles.

Note:
    Skills are protocol-based abstractions that users implement.
    This module provides factory functions for skill utilities and configurations,
    not for skill instances themselves.

Extension Point:
    This module is designed for extension. Add your custom skill
    implementations and register them here if needed.
"""

# ============================================================================
# EXTEND HERE: Bring Your Own Skill Implementations
# ============================================================================
# This is the extension point for custom skill implementations.
#
# To add your own skill type:
# 1. Implement the Skill protocol (see cemaf.skills.protocols)
# 2. Add a factory function below
# 3. Optionally add a config-based factory
#
# Example (LLM Skill):
#   from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings

#   from cemaf.llm.protocols import LLMClient
#   from cemaf.core.types import SkillID
#
#   def create_llm_skill(
#       skill_id: SkillID,
#       llm: LLMClient,
#       system_prompt: str | None = None,
#   ) -> Skill:
#       from your_package import LLMSkill
#       return LLMSkill(
#           skill_id=skill_id,
#           llm=llm,
#           system_prompt=system_prompt or "You are a helpful assistant."
#       )
#
#   def create_llm_skill_from_config(
#       skill_id: SkillID,
#       system_prompt: str | None = None,
#   , settings: Settings | None = None) -> Skill:
#       from cemaf.llm.factories import create_llm_client_from_config
#       llm = create_llm_client_from_config()
#       return create_llm_skill(skill_id, llm, system_prompt)
#
# Example (Tool Composition Skill):
#   def create_tool_skill(
#       skill_id: SkillID,
#       tools: tuple[Tool, ...],
#   ) -> Skill:
#       from your_package import ToolCompositionSkill
#       return ToolCompositionSkill(skill_id=skill_id, tools=tools)
#
# Example (Retrieval Skill):
#   def create_retrieval_skill(
#       skill_id: SkillID,
#       vector_store: VectorStore,
#       top_k: int = 5,
#   ) -> Skill:
#       from your_package import RetrievalSkill
#       return RetrievalSkill(
#           skill_id=skill_id,
#           vector_store=vector_store,
#           top_k=top_k
#       )
#
#   def create_retrieval_skill_from_config(skill_id: SkillID, settings: Settings | None = None) -> Skill:
#       from cemaf.retrieval.factories import create_vector_store_from_config
#       vector_store = create_vector_store_from_config()
#       top_k = int(os.getenv("CEMAF_SKILLS_RETRIEVAL_TOP_K", "5"))
#       return create_retrieval_skill(skill_id, vector_store, top_k)
#
# Example (Code Execution Skill):
#   def create_code_execution_skill(
#       skill_id: SkillID,
#       allowed_languages: tuple[str, ...] = ("python",),
#       timeout_seconds: float = 30.0,
#   ) -> Skill:
#       from your_package import CodeExecutionSkill
#       return CodeExecutionSkill(
#           skill_id=skill_id,
#           allowed_languages=allowed_languages,
#           timeout_seconds=timeout_seconds,
#       )
# ============================================================================


# Placeholder for future built-in skill implementations
def create_skill_from_config(skill_type: str, settings: Settings | None = None) -> None:
    """
    Create Skill from environment configuration.

    Args:
        skill_type: Type of skill to create

    Raises:
        ValueError: No built-in skill implementations available

    Note:
        This is a placeholder. Add your own skill implementations
        in the "EXTEND HERE" section above.
    """
    raise ValueError(
        f"No built-in skill implementations for type: {skill_type}. "
        f"To add your own, extend this module in cemaf/skills/factories.py"
    )
