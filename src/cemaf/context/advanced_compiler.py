"""
Advanced Context Compiler - Extends PriorityContextCompiler with summarization.
"""

import logging

from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
)
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import (
    AdvancedCompilerConfig,
    CompiledContext,
    ContextSource,
    TokenEstimator,
)
from cemaf.llm.protocols import LLMClient

logger = logging.getLogger(__name__)


class AdvancedContextCompiler:
    """
    An advanced context compiler that uses an LLM to summarize low-priority
    sources when the token budget is exceeded.

    Uses composition instead of inheritance for maximum flexibility.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        token_estimator: TokenEstimator,
        config: AdvancedCompilerConfig | None = None,
        algorithm: ContextSelectionAlgorithm | None = None,
    ) -> None:
        """
        Initialize advanced context compiler.

        Args:
            llm_client: LLM client for summarization (required)
            token_estimator: Token estimation strategy (required)
            config: Compiler configuration (optional, uses defaults if not provided)
            algorithm: Selection algorithm (optional)
                - If None (default): Pure summarization mode (includes all sources)
                - If provided: Two-stage mode (algorithm selects, then summarization fallback)
        """
        self._llm_client = llm_client
        self._estimator = token_estimator
        self._config = config or AdvancedCompilerConfig()
        self._algorithm = algorithm  # None for Mode 1, CustomAlgorithm() for Mode 2

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        """
        Compiles context with dual-mode behavior:

        - Mode 1 (default, algorithm=None): Pure summarization
          Includes all sources, summarizes low-priority ones to fit budget

        - Mode 2 (algorithm provided): Two-stage optimization
          Uses algorithm to select best sources, then summarization fallback
        """
        # Gather all sources (sorted by priority)
        all_sources = self._gather_all_sources(artifacts, memories, priorities)

        # MODE SELECTION: Check if algorithm should be used
        if self._algorithm is not None:
            # MODE 2: Two-stage (algorithm + summarization)
            return await self._compile_two_stage(all_sources, budget)
        else:
            # MODE 1: Pure summarization (current behavior)
            return await self._compile_pure_summarization(all_sources, budget)

    async def _compile_pure_summarization(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> CompiledContext:
        """
        Mode 1: Pure summarization - includes all sources.

        Current default behavior - maintains backward compatibility.
        """
        # Calculate total tokens if we included everything
        total_tokens = sum(s.token_count for s in sources)

        # Create initial context with ALL sources
        initial_context = CompiledContext(
            sources=tuple(sources),
            total_tokens=total_tokens,
            budget=budget,
            metadata={
                "compilation_mode": "pure_summarization",
                "all_sources_included": True,
            },
        )

        # If within budget, return as-is
        if initial_context.within_budget():
            return initial_context

        # Otherwise, summarize low-priority sources to fit budget
        return await self._summarize_to_fit_budget(initial_context)

    async def _compile_two_stage(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> CompiledContext:
        """
        Mode 2: Two-stage optimization - algorithm selection then summarization.

        Used when algorithm parameter is provided.
        Enables optimal selection strategies for performance-critical scenarios.
        """
        # Stage 1: Use algorithm to select sources
        selection_result = self._algorithm.select_sources(sources, budget)

        # Create initial context with selected sources
        initial_context = CompiledContext(
            sources=selection_result.selected_sources,
            total_tokens=selection_result.total_tokens,
            budget=budget,
            metadata={
                **selection_result.metadata,
                "compilation_mode": "two_stage",
                "algorithm_used": selection_result.selection_method,
            },
        )

        # If selected sources fit within budget, return as-is
        if initial_context.within_budget():
            return initial_context

        # Stage 2: If still over budget, apply summarization fallback
        # This handles cases where algorithm's selection is close to budget
        # but a few large sources push it over
        summarized = await self._summarize_to_fit_budget(initial_context)

        # Update metadata to indicate summarization was applied
        return CompiledContext(
            sources=summarized.sources,
            total_tokens=summarized.total_tokens,
            budget=summarized.budget,
            metadata={
                **initial_context.metadata,
                "summarization_applied": True,
                "final_mode": "two_stage_with_summarization",
            },
        )

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
                total_tokens = total_tokens - original_token_count + summarized_source.token_count
                mutable_sources[i] = summarized_source
            else:
                total_tokens -= source.token_count
                mutable_sources[i] = None  # type: ignore

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

        target_summary_tokens = self._estimate_target_summary_tokens(source, budget)
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
            logger.warning(f"Summarization failed for source '{source.key}': {e}")

        return None

    def _estimate_target_summary_tokens(
        self,
        source: ContextSource,
        budget: TokenBudget,
    ) -> int:
        """
        Estimates the target summary tokens.

        Uses configured target from AdvancedCompilerConfig.
        """
        return self._config.target_summary_tokens
