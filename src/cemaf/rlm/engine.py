"""
Recursive query engine for RLM.

Implements divide-and-conquer strategy for querying large context:
1. Base case: If chunks fit in budget, make single LLM call
2. Recursive case: Split chunks, query each, aggregate results
3. Respect max_depth to prevent infinite recursion
"""

import asyncio
from typing import Any

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, ContextCompiler
from cemaf.core.types import TokenCount
from cemaf.llm.protocols import LLMClient, Message
from cemaf.observability import get_logger
from cemaf.rlm.protocols import ContextChunk, RecursiveQueryResult

logger = get_logger("rlm.engine")


class DivideAndConquerQueryEngine:
    """
    Simple divide-and-conquer query engine.

    Strategy:
    - Base case: If chunks fit in budget, make single LLM call
    - Recursive case: Split chunks, query each recursively, aggregate
    - Respect max_depth to prevent infinite recursion

    Example:
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=3)
        result = await engine.query(
            instruction="Find all mentions of CEMAF",
            chunks=chunks,
            budget=TokenBudget(max_tokens=4000),
        )
    """

    def __init__(
        self,
        llm_client: LLMClient,
        compiler: ContextCompiler,
        max_depth: int = 3,
    ) -> None:
        """
        Initialize divide-and-conquer query engine.

        Args:
            llm_client: LLM client for queries
            compiler: Context compiler for budget enforcement
            max_depth: Maximum recursion depth (default=3)
        """
        self._llm = llm_client
        self._compiler = compiler
        self._max_depth = max_depth

    async def query(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        budget: TokenBudget,
        max_depth: int | None = None,
        depth: int = 0,
    ) -> RecursiveQueryResult:
        """
        Execute recursive query with divide-and-conquer.

        Args:
            instruction: Query instruction for the LLM
            chunks: Chunks to query
            budget: Token budget to respect
            max_depth: Maximum recursion depth (default=engine's max_depth)
            depth: Current recursion depth (internal, default=0)

        Returns:
            RecursiveQueryResult with answer and metadata
        """
        max_depth = max_depth if max_depth is not None else self._max_depth

        if not chunks:
            logger.warning("RLM query with no chunks", depth=depth, instruction_len=len(instruction))
            return RecursiveQueryResult.fail(
                error="No chunks to query",
                depth_reached=depth,
            )

        # Convert chunks to (key, content) pairs for compiler
        chunk_data = tuple((chunk.chunk_id, chunk.content) for chunk in chunks)
        compiled = await self._compiler.compile(
            artifacts=chunk_data,
            memories=(),
            budget=budget,
        )

        if compiled.within_budget():
            logger.debug(
                "RLM single query (within budget)",
                depth=depth,
                num_chunks=len(chunks),
                compiled_tokens=compiled.total_tokens,
                budget_tokens=budget.max_tokens,
            )
            result = await self._single_query(instruction, chunks, compiled)

            # If LLM call failed, return failure (not success with error message)
            if not result["found"]:
                logger.warning(
                    "RLM single query failed",
                    depth=depth,
                    num_chunks=len(chunks),
                    error=result["answer"],
                )
                return RecursiveQueryResult.fail(
                    error=result["answer"],
                    depth_reached=depth,
                    chunks_examined=len(chunks),
                    llm_calls_made=1,
                    metadata={"strategy": "single_query"},
                )

            logger.info(
                "RLM single query succeeded",
                depth=depth,
                num_chunks=len(chunks),
                tokens_used=result["tokens_used"],
            )
            return RecursiveQueryResult.ok(
                answer=result["answer"],
                relevant_chunks=tuple(chunks),
                depth_reached=depth,
                chunks_examined=len(chunks),
                llm_calls_made=1,
                total_tokens_used=TokenCount(result["tokens_used"]),
                metadata={
                    "strategy": "single_query",
                    "compiled_tokens": compiled.total_tokens,
                },
            )

        if depth >= max_depth or len(chunks) == 1:
            # Fallback: process budget-sized batches for partial coverage
            reason = "max_depth_reached" if depth >= max_depth else "single_large_chunk"
            logger.warning(
                "RLM partial coverage fallback",
                depth=depth,
                max_depth=max_depth,
                num_chunks=len(chunks),
                reason=reason,
            )
            return await self._query_partial_coverage(
                instruction=instruction,
                chunks=chunks,
                budget=budget,
                depth=depth,
                reason=reason,
            )

        mid = len(chunks) // 2
        left_chunks = chunks[:mid]
        right_chunks = chunks[mid:]

        logger.debug(
            "RLM dividing chunks",
            depth=depth,
            total_chunks=len(chunks),
            left_chunks=len(left_chunks),
            right_chunks=len(right_chunks),
        )

        # Process left and right branches in parallel
        left_result, right_result = await asyncio.gather(
            self.query(
                instruction=instruction,
                chunks=left_chunks,
                budget=budget,
                max_depth=max_depth,
                depth=depth + 1,
            ),
            self.query(
                instruction=instruction,
                chunks=right_chunks,
                budget=budget,
                max_depth=max_depth,
                depth=depth + 1,
            ),
        )

        if not left_result.success:
            logger.warning(
                "RLM left branch failed",
                depth=depth,
                left_chunks=len(left_chunks),
                error=left_result.error,
            )
            return left_result

        if not right_result.success:
            logger.warning(
                "RLM right branch failed",
                depth=depth,
                right_chunks=len(right_chunks),
                error=right_result.error,
            )
            return right_result

        logger.debug(
            "RLM aggregating results",
            depth=depth,
            left_depth=left_result.depth_reached,
            right_depth=right_result.depth_reached,
            left_llm_calls=left_result.llm_calls_made,
            right_llm_calls=right_result.llm_calls_made,
        )

        aggregated = await self._aggregate_results(
            instruction=instruction,
            left_result=left_result,
            right_result=right_result,
            budget=budget,
        )

        total_llm_calls = left_result.llm_calls_made + right_result.llm_calls_made + 1
        total_tokens = (
            int(left_result.total_tokens_used)
            + int(right_result.total_tokens_used)
            + aggregated["tokens_used"]
        )

        logger.info(
            "RLM divide-and-conquer succeeded",
            depth=depth,
            total_chunks=len(chunks),
            chunks_examined=left_result.chunks_examined + right_result.chunks_examined,
            total_llm_calls=total_llm_calls,
            total_tokens=total_tokens,
            max_recursion_depth=max(left_result.depth_reached, right_result.depth_reached),
        )

        total_examined = left_result.chunks_examined + right_result.chunks_examined
        coverage = total_examined / len(chunks) if chunks else 0.0

        return RecursiveQueryResult.ok(
            answer=aggregated["answer"],
            relevant_chunks=(
                *left_result.relevant_chunks,
                *right_result.relevant_chunks,
            ),
            depth_reached=max(left_result.depth_reached, right_result.depth_reached),
            chunks_examined=total_examined,
            llm_calls_made=total_llm_calls,
            total_tokens_used=TokenCount(total_tokens),
            metadata={
                "strategy": "divide_and_conquer",
                "left_chunks": len(left_chunks),
                "right_chunks": len(right_chunks),
                "coverage_ratio": coverage,
            },
        )

    async def _single_query(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        compiled: CompiledContext,
    ) -> dict[str, Any]:
        """Execute single LLM query with all chunks."""
        context_content = "\n\n---\n\n".join(f"[Chunk {chunk.chunk_id}]\n{chunk.content}" for chunk in chunks)

        prompt = f"""{instruction}

Context:
{context_content}

Provide your answer based on the context above. If the information is not found in the
context, explicitly state that."""

        messages = [Message.user(prompt)]
        result = await self._llm.complete(messages)

        if not result.success:
            return {
                "answer": f"Error: {result.error}",
                "found": False,
                "tokens_used": 0,
            }

        return {
            "answer": result.content if isinstance(result.content, str) else str(result.content),
            "found": True,
            "tokens_used": int(result.total_tokens),
        }

    async def _query_partial_coverage(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        budget: TokenBudget,
        depth: int,
        reason: str,
    ) -> RecursiveQueryResult:
        """Process budget-sized batches and aggregate for partial coverage."""
        available = budget.available_tokens
        batch: list[ContextChunk] = []
        batch_tokens = 0
        answers: list[str] = []
        total_tokens_used = 0
        llm_calls = 0
        examined = 0

        for chunk in chunks:
            token_est = int(chunk.token_count) if chunk.token_count else len(chunk.content) // 4
            if batch_tokens + token_est > available and batch:
                # Process current batch
                result = await self._single_query_from_chunks(instruction=instruction, chunks_list=batch)
                llm_calls += 1
                examined += len(batch)
                total_tokens_used += result["tokens_used"]
                if result["found"]:
                    answers.append(result["answer"])
                batch = []
                batch_tokens = 0
            batch.append(chunk)
            batch_tokens += token_est

        # Process remaining batch
        if batch:
            result = await self._single_query_from_chunks(instruction=instruction, chunks_list=batch)
            llm_calls += 1
            examined += len(batch)
            total_tokens_used += result["tokens_used"]
            if result["found"]:
                answers.append(result["answer"])

        coverage = examined / len(chunks) if chunks else 0.0

        if not answers:
            return RecursiveQueryResult.fail(
                error="Partial coverage query produced no results",
                depth_reached=depth,
                chunks_examined=examined,
                llm_calls_made=llm_calls,
                metadata={"strategy": "partial_coverage", "reason": reason},
            )

        # Aggregate if multiple batches
        if len(answers) == 1:
            final_answer = answers[0]
        else:
            agg = await self._aggregate_answer_list(instruction=instruction, answers=answers, budget=budget)
            llm_calls += 1
            total_tokens_used += agg["tokens_used"]
            final_answer = agg["answer"]

        logger.info(
            "RLM partial coverage succeeded",
            depth=depth,
            reason=reason,
            total_chunks=len(chunks),
            chunks_examined=examined,
            coverage_ratio=coverage,
            batches=len(answers),
        )

        return RecursiveQueryResult.ok(
            answer=final_answer,
            relevant_chunks=tuple(chunks[:examined]),
            depth_reached=depth,
            chunks_examined=examined,
            llm_calls_made=llm_calls,
            total_tokens_used=TokenCount(total_tokens_used),
            metadata={
                "strategy": "partial_coverage",
                "reason": reason,
                "coverage_ratio": coverage,
            },
        )

    async def _single_query_from_chunks(
        self,
        instruction: str,
        chunks_list: list[ContextChunk],
    ) -> dict[str, Any]:
        """Execute a single LLM query from a list of chunks."""
        context_content = "\n\n---\n\n".join(f"[Chunk {c.chunk_id}]\n{c.content}" for c in chunks_list)
        prompt = f"""{instruction}

Context:
{context_content}

Provide your answer based on the context above."""

        messages = [Message.user(prompt)]
        result = await self._llm.complete(messages)

        if not result.success:
            return {"answer": f"Error: {result.error}", "found": False, "tokens_used": 0}

        return {
            "answer": result.content if isinstance(result.content, str) else str(result.content),
            "found": True,
            "tokens_used": int(result.total_tokens),
        }

    async def _aggregate_answer_list(
        self,
        instruction: str,
        answers: list[str],
        budget: TokenBudget,
    ) -> dict[str, Any]:
        """Aggregate multiple partial answers into one."""
        parts = "\n\n".join(f"Part {i + 1}:\n{a}" for i, a in enumerate(answers))
        prompt = f"""{instruction}

I have gathered information from {len(answers)} batches:

{parts}

Synthesize these into a single coherent response."""

        messages = [Message.user(prompt)]
        result = await self._llm.complete(messages)

        if not result.success:
            return {"answer": "; ".join(answers), "tokens_used": 0}

        return {
            "answer": result.content if isinstance(result.content, str) else str(result.content),
            "tokens_used": int(result.total_tokens),
        }

    async def _aggregate_results(
        self,
        instruction: str,
        left_result: RecursiveQueryResult,
        right_result: RecursiveQueryResult,
        budget: TokenBudget,
    ) -> dict[str, Any]:
        """Aggregate results from left and right recursive queries."""
        left_answer = left_result.answer or "No information found"
        right_answer = right_result.answer or "No information found"

        prompt = f"""{instruction}

I have gathered information from two parts of the context:

Part 1:
{left_answer}

Part 2:
{right_answer}

Please synthesize these answers into a single, coherent response that addresses the original question."""

        messages = [Message.user(prompt)]
        result = await self._llm.complete(messages)

        if not result.success:
            partial_info = f"{left_answer}; {right_answer}"
            return {
                "answer": f"Aggregation failed: {result.error}. Partial results: {partial_info}",
                "tokens_used": 0,
            }

        return {
            "answer": result.content if isinstance(result.content, str) else str(result.content),
            "tokens_used": int(result.total_tokens),
        }
