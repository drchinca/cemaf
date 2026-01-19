"""
Recursive query engine for RLM.

Implements divide-and-conquer strategy for querying large context:
1. Base case: If chunks fit in budget, make single LLM call
2. Recursive case: Split chunks, query each, aggregate results
3. Respect max_depth to prevent infinite recursion
"""

from typing import Any

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, ContextCompiler
from cemaf.core.types import TokenCount
from cemaf.llm.protocols import LLMClient, Message
from cemaf.rlm.protocols import ContextChunk, RecursiveQueryResult


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
            result = await self._single_query(instruction, chunks, compiled)

            # If LLM call failed, return failure (not success with error message)
            if not result["found"]:
                return RecursiveQueryResult.fail(
                    error=result["answer"],
                    depth_reached=depth,
                    chunks_examined=len(chunks),
                    llm_calls_made=1,
                    metadata={"strategy": "single_query"},
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
            # Fallback when max depth reached OR single chunk that doesn't fit
            # Single chunk case prevents infinite recursion
            result = await self._query_first_chunk_only(instruction, chunks, budget)
            reason = "max_depth_reached" if depth >= max_depth else "single_large_chunk"

            # If LLM call failed, return failure
            if not result["found"]:
                return RecursiveQueryResult.fail(
                    error=result["answer"],
                    depth_reached=depth,
                    chunks_examined=1,
                    llm_calls_made=1,
                    metadata={"strategy": "fallback", "reason": reason},
                )

            return RecursiveQueryResult.ok(
                answer=result["answer"],
                relevant_chunks=tuple(chunks[:1]),
                depth_reached=depth,
                chunks_examined=1,
                llm_calls_made=1,
                total_tokens_used=TokenCount(result["tokens_used"]),
                metadata={
                    "strategy": "fallback",
                    "reason": reason,
                },
            )

        mid = len(chunks) // 2
        left_chunks = chunks[:mid]
        right_chunks = chunks[mid:]

        left_result = await self.query(
            instruction=instruction,
            chunks=left_chunks,
            budget=budget,
            max_depth=max_depth,
            depth=depth + 1,
        )

        right_result = await self.query(
            instruction=instruction,
            chunks=right_chunks,
            budget=budget,
            max_depth=max_depth,
            depth=depth + 1,
        )

        if not left_result.success:
            return left_result

        if not right_result.success:
            return right_result

        aggregated = await self._aggregate_results(
            instruction=instruction,
            left_result=left_result,
            right_result=right_result,
            budget=budget,
        )

        return RecursiveQueryResult.ok(
            answer=aggregated["answer"],
            relevant_chunks=(
                *left_result.relevant_chunks,
                *right_result.relevant_chunks,
            ),
            depth_reached=max(left_result.depth_reached, right_result.depth_reached),
            chunks_examined=(left_result.chunks_examined + right_result.chunks_examined),
            llm_calls_made=(left_result.llm_calls_made + right_result.llm_calls_made + 1),
            total_tokens_used=TokenCount(
                int(left_result.total_tokens_used)
                + int(right_result.total_tokens_used)
                + aggregated["tokens_used"]
            ),
            metadata={
                "strategy": "divide_and_conquer",
                "left_chunks": len(left_chunks),
                "right_chunks": len(right_chunks),
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

    async def _query_first_chunk_only(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        budget: TokenBudget,
    ) -> dict[str, Any]:
        """
        Query only the first chunk when recursion limit reached.

        This is a fallback strategy used when:
        1. Max recursion depth is reached
        2. Single large chunk that doesn't fit in budget

        Only processes the first chunk to provide partial results.
        """
        first_chunk = chunks[0]
        prompt = f"""{instruction}

Context (partial - showing first chunk only due to size constraints):
[Chunk {first_chunk.chunk_id}]
{first_chunk.content}

Note: This is only a portion of the full context. Provide your best answer based on this excerpt."""

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
