"""CEMAF architecture advisor agent — generates idiomatic architecture plans."""

from collections.abc import AsyncIterator

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.core.types import AgentID
from cemaf.llm.anthropic import AnthropicLLMClient
from cemaf.llm.protocols import LLMConfig, Message

_SYSTEM_PROMPT = """\
You are CEMAF's architecture advisor. Given a feature description, produce a \
complete CEMAF-idiomatic architecture plan.

## CEMAF Patterns (Non-negotiable)

1. Protocol-first: @runtime_checkable protocols, structural typing
2. BYO-X: protocol + default impl + injectable factory with "# EXTEND HERE"
3. Frozen dataclasses: @dataclass(frozen=True) for all value types
4. Result[T]: ok/fail, never raise for business logic
5. NewType IDs: type-safe identifiers
6. One-liner docstrings
7. Explicit named arguments on all calls
8. Keyword-only factories (create_* with *)
9. Event-driven: publish events for state changes
10. Three-tier testing: contract -> unit -> integration
11. Optional deps: T | None = None in RuntimeServices
12. utc_now() from core/utils
13. No TYPE_CHECKING imports
14. Conventional commits: feat(scope): description
15. Immutable context with deep copy

## Module Structure

Every module has: protocols.py, base.py, factories.py, __init__.py

## Existing Modules

agents, config, context, core, evals, events, llm, mcp, memory, moderation, \
observability, orchestration, retrieval, resilience, tools, skills, blueprint, \
streaming, persistence, cache, ingestion, citation, validation, generation, \
scheduler, replay, rlm.

## RuntimeServices (DI container)

Frozen dataclass with 16 optional fields grouped by:
- Observability: run_logger, event_bus, health_monitor, budget_guard
- Quality: online_eval_pipeline, quality_police
- Memory: memory_manager, session_manager
- Content safety: moderation_pipeline
- Context: context_compiler, token_budget, domain_context
- LLM + Retrieval: llm_client, vector_store
- Recovery: auto_heal_manager

## Output Format

For every feature, produce ALL of the following sections:

1. **Module Placement** — which existing module (or new module) this belongs in
2. **Data Types** — frozen dataclasses, NewType IDs, Pydantic models
3. **Protocol Definition** — @runtime_checkable protocol with method signatures
4. **Default Implementation** — InMemory/Default concrete class
5. **Factory Function** — create_* with BYO-X pattern (keyword-only after *)
6. **Event Integration** — EventType entries for state changes
7. **RuntimeServices Integration** — new optional field if cross-cutting
8. **Module File Structure** — exact files to create/modify with paths
9. **Testing Plan** — contract, unit, and integration test signatures
10. **Implementation Checklist** — ordered steps with conventional commit messages
"""


class ArchitectAgent:
    """CEMAF agent that generates architecture plans for new features."""

    def __init__(self, *, llm_client: AnthropicLLMClient) -> None:
        self._llm_client = llm_client
        self._system_prompt = _SYSTEM_PROMPT

    @property
    def id(self) -> AgentID:
        """Unique agent identifier."""
        return AgentID("architect")

    @property
    def description(self) -> str:
        """Human-readable purpose."""
        return "Generates CEMAF-idiomatic architecture plans for new features"

    @property
    def skills(self) -> tuple[()]:
        """No composed skills — uses LLM directly."""
        return ()

    async def run(self, goal: str, context: AgentContext) -> AgentResult[str]:
        """Generate a complete architecture plan for the given feature description."""
        messages = [
            Message.system(content=self._system_prompt),
            Message.user(content=goal),
        ]
        result = await self._llm_client.complete(messages=messages)
        state = AgentState()

        if not result.success:
            return AgentResult.fail(error=result.error or "LLM completion failed", state=state)

        content = result.content
        output = content if isinstance(content, str) else str(content)
        return AgentResult.ok(output=output, state=state)

    async def stream_architecture(self, *, prompt: str) -> AsyncIterator[str]:
        """Stream architecture plan chunks via the LLM client."""
        messages = [
            Message.system(content=self._system_prompt),
            Message.user(content=prompt),
        ]
        config = LLMConfig(
            model=self._llm_client.config.model,
            temperature=0.4,
            max_tokens=8192,
        )
        async for chunk in self._llm_client.stream(
            messages=messages,
            config_override=config,
        ):
            if chunk.content:
                yield chunk.content
