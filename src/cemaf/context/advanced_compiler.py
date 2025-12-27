"""
Advanced Context Compiler - Extends PriorityContextCompiler with summarization.
"""

from __future__ import annotations

import logging

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import (
    CompiledContext,
    ContextSource,
    PriorityContextCompiler,
    TokenEstimator,
)
from cemaf.llm.protocols import LLMClient


logger = logging.getLogger(__name__)


class AdvancedContextCompiler(PriorityContextCompiler):
    """
    An advanced context compiler that uses an LLM to summarize low-priority
    sources when the token budget is exceeded.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        """
        Initializes the AdvancedContextCompiler.
        """
        super().__init__(token_estimator)
        self._llm_client = llm_client

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        """
        Compiles the context, applying summarization if the budget is exceeded.
        
        First gathers ALL sources (without filtering), then summarizes if needed.
        """
        # First, gather all sources without filtering (to allow summarization)
        all_sources = self._gather_all_sources(artifacts, memories, priorities)
        
        # Calculate total tokens
        total_tokens = sum(s.token_count for s in all_sources)
        
        # Create initial context with all sources
        initial_context = CompiledContext(
            sources=tuple(all_sources),
            total_tokens=total_tokens,
            budget=budget,
        )

        # If within budget, return as-is
        if initial_context.within_budget():
            return initial_context
        
        # Otherwise, summarize to fit budget
        return await self._summarize_to_fit_budget(initial_context)
    
    def _gather_all_sources(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        priorities: dict[str, int] | None,
    ) -> list[ContextSource]:
        """Gather all sources without filtering by budget."""
        priorities = priorities or {}
        sources: list[ContextSource] = []
        
        # Create sources from artifacts and memories
        for key, content in artifacts:
            tokens = self._estimator.estimate(content)
            priority = priorities.get(key, 0)
            sources.append(
                ContextSource(
                    type="artifact",
                    key=key,
                    content=content,
                    token_count=tokens,
                    priority=priority,
                )
            )

        for key, content in memories:
            tokens = self._estimator.estimate(content)
            priority = priorities.get(key, -1)
            sources.append(
                ContextSource(
                    type="memory",
                    key=key,
                    content=content,
                    token_count=tokens,
                    priority=priority,
                )
            )

        # Sort by priority (descending) - higher priority first
        sources.sort(key=lambda s: s.priority, reverse=True)
        
        return sources

    async def _summarize_to_fit_budget(self, context: CompiledContext) -> CompiledContext:
        """
        Summarizes sources to fit the budget.
        """
        mutable_sources = list(context.sources)
        total_tokens = context.total_tokens

        # Sort sources by priority (ascending) to summarize lowest priority first
        mutable_sources.sort(key=lambda s: s.priority)

        for i, source in enumerate(mutable_sources):
            if total_tokens <= context.budget.available_tokens:
                break

            summarized_source = await self._summarize_source(source, context.budget)

            if summarized_source:
                original_token_count = source.token_count
                total_tokens = (
                    total_tokens
                    - original_token_count
                    + summarized_source.token_count
                )
                mutable_sources[i] = summarized_source
            else:
                total_tokens -= source.token_count
                mutable_sources[i] = None # type: ignore
        
        final_sources = tuple(s for s in mutable_sources if s is not None)
        
        total_tokens = sum(s.token_count for s in final_sources)

        return CompiledContext(
            sources=final_sources,
            total_tokens=total_tokens,
            budget=context.budget,
            metadata={"summarized": True},
        )

    async def _summarize_source(
        self,
        source: ContextSource,
        budget: TokenBudget,
    ) -> ContextSource | None:
        """
        Summarizes a source.
        """
        from cemaf.core.constants import SUMMARIZATION_PROMPT_TEMPLATE
        from cemaf.llm.protocols import Message

        target_summary_tokens = self._estimate_target_summary_tokens(
            source, budget
        )
        prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
            target_summary_tokens=target_summary_tokens, text=source.content
        )

        try:
            result = await self._llm_client.complete([Message.user(prompt)])
            if result.success and result.message:
                summary_text = result.message.content
                return ContextSource(
                    type=source.type,
                    key=f"summarized_{source.key}",
                    content=summary_text,
                    token_count=self._estimator.estimate(summary_text),
                    priority=source.priority,
                    metadata={"original_key": source.key},
                )
        except Exception as e:
            logger.warning(
                f"Summarization failed for source '{source.key}': {e}"
            )

        return None

    def _estimate_target_summary_tokens(
        self,
        source: ContextSource,
        budget: TokenBudget,
    ) -> int:
        """
        Estimates the target summary tokens.
        """
        return 50
