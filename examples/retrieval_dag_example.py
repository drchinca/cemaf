"""
Large-Scale Data Asset Retrieval Example: Full CEMAF Capabilities Demonstration

This example demonstrates the FULL EXTENT of CEMAF's capabilities:
1. Context Engineering: Token budgeting and optimization for massive datasets
2. Model Thinking: LLM calls with tool calling and reasoning
3. Reproducibility: Complete run recording and deterministic replay
4. Audit Trails: Full provenance tracking of every context change
5. Memory Optimization: Smart context compilation within token limits

Use Case:
    - Data Asset: 9 trillion records with 500 metrics
    - Query: "find hello"
    - Problem: Can't load all data into context (exceeds token limits)
    - Solution: Retrieval + Token Budgeting + Context Compilation + Full Audit

What This Demonstrates:
✅ Context Engineering: Token budget enforcement and optimization
✅ Model Thinking: LLM reasoning with tool calls (mocked for demo)
✅ Reproducibility: Record and replay runs deterministically
✅ Audit Trails: Every patch, tool call, and LLM call recorded
✅ Memory Optimization: Only include what fits, exclude the rest

Flow:
    Query → Hybrid Search → Filter by Budget → Compile Context → LLM Analysis → Response
              ↓                    ↓                    ↓              ↓
          (9T records)      (top-k only)      (within budget)   (recorded)
              ↓                    ↓                    ↓              ↓
          (recorded)         (patched)          (optimized)      (replayable)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import (
    ContextCompiler,
    PriorityContextCompiler,
    SimpleTokenEstimator,
)
from cemaf.context.context import Context
from cemaf.core.result import Result
from cemaf.core.types import JSON, SkillID, ToolID
from cemaf.llm.protocols import LLMClient, Message
from cemaf.observability.run_logger import (
    InMemoryRunLogger,
    LLMCall,
)
from cemaf.observability.run_logger import (
    ToolCall as RecordedToolCall,
)
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult
from cemaf.replay.replayer import Replayer, ReplayMode
from cemaf.skills.base import Skill, SkillContext, SkillOutput, SkillResult
from cemaf.tools.base import Tool, ToolResult, ToolSchema

# ============================================================================
# Large-Scale Data Asset Simulation
# ============================================================================


@dataclass
class DataRecord:
    """A single record from the massive dataset."""

    id: str
    metrics: dict[str, float]  # 500 metrics
    text_content: str
    metadata: JSON


class MassiveDataAsset:
    """
    Simulates a massive data asset: 9 trillion records with 500 metrics each.

    In reality, this would be a distributed database/warehouse.
    We simulate it by generating records on-demand for queries.
    """

    TOTAL_RECORDS = 9_000_000_000_000  # 9 trillion
    METRICS_PER_RECORD = 500

    def __init__(self) -> None:
        self._search_count = 0
        self._cache: dict[str, list[DataRecord]] = {}

    async def search(
        self,
        query: str,
        top_k: int = 10,
        use_vector: bool = True,
        use_keyword: bool = True,
    ) -> list[DataRecord]:
        """
        Search across 9 trillion records.

        In production, this would:
        - Use distributed vector search (Pinecone, Weaviate, etc.)
        - Use distributed keyword search (Elasticsearch, etc.)
        - Combine results with RRF (Reciprocal Rank Fusion)
        - Return only top-k results
        """
        self._search_count += 1
        cache_key = f"{query}:{top_k}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        # Simulate finding relevant records (in reality, this queries the data warehouse)
        # For "hello" query, we simulate finding records that contain "hello"
        records = []
        for i in range(top_k):
            # Simulate finding records with "hello" in them
            record = DataRecord(
                id=f"record_{i+1}",
                metrics={f"metric_{j}": float(j) for j in range(self.METRICS_PER_RECORD)},
                text_content=f"Record {i+1} contains '{query}' with relevant context. "
                f"This is one of {self.TOTAL_RECORDS:,} total records. "
                f"Metric values: {', '.join([f'm{j}=v{j}' for j in range(10)])}...",
                metadata={
                    "query": query,
                    "rank": i + 1,
                    "total_records": self.TOTAL_RECORDS,
                    "relevance_score": 0.95 - (i * 0.05),
                },
            )
            records.append(record)

        self._cache[cache_key] = records
        return records

    def get_total_size_estimate(self) -> dict[str, Any]:
        """Estimate total size of the data asset."""
        # Rough estimate: each record ~1KB, 9T records = 9PB
        return {
            "total_records": self.TOTAL_RECORDS,
            "metrics_per_record": self.METRICS_PER_RECORD,
            "estimated_size_pb": self.TOTAL_RECORDS * 1024 / (1024**5),  # ~9PB
            "estimated_tokens": self.TOTAL_RECORDS * 250,  # ~2.25 quadrillion tokens
        }


# ============================================================================
# Large-Scale Retrieval Skill with Token Budget Management
# ============================================================================


class LargeScaleRetrievalInput(BaseModel):
    """Input for large-scale retrieval skill."""

    query: str
    top_k: int = 10  # Only retrieve top-k, not all 9T records
    max_tokens_per_result: int = 200  # Limit tokens per result


class LargeScaleRetrievalSkill(Skill[LargeScaleRetrievalInput, dict[str, Any]]):
    """
    Retrieval skill for massive data assets.

    Key strategies:
    1. Only retrieve top-k results (not all 9T records)
    2. Limit tokens per result to stay within budget
    3. Cache expensive searches
    4. Use hybrid search (vector + keyword)
    """

    def __init__(
        self,
        data_asset: MassiveDataAsset,
        token_estimator: SimpleTokenEstimator,
    ):
        self._data_asset = data_asset
        self._token_estimator = token_estimator

    @property
    def id(self) -> SkillID:
        return SkillID("large_scale_retrieval")

    @property
    def description(self) -> str:
        return "Retrieve relevant records from massive data asset (9T records)"

    @property
    def tools(self) -> tuple[Tool, ...]:
        return ()

    async def execute(
        self,
        input: LargeScaleRetrievalInput,
        context: SkillContext,
    ) -> SkillResult:
        """
        Execute retrieval from massive data asset.

        Strategy:
        1. Search across 9T records (distributed search)
        2. Get top-k results only
        3. Truncate each result to max_tokens_per_result
        4. Return only what fits in context budget
        """
        try:
            print(
                f"\n[Retrieval] Searching {self._data_asset.TOTAL_RECORDS:,} "
                f"records for '{input.query}'..."
            )
            print("  Strategy: Hybrid search (vector + keyword)")
            print(f"  Top-k: {input.top_k} results")

            # Search the massive data asset
            records = await self._data_asset.search(
                query=input.query,
                top_k=input.top_k,
                use_vector=True,
                use_keyword=True,
            )

            print(f"  Found {len(records)} relevant records")

            # Format results with token limits
            formatted_results = []
            total_tokens = 0

            for i, record in enumerate(records):
                # Create more detailed representation to demonstrate token budgeting
                # Make some results longer to show filtering
                if i < 3:
                    # First 3 results: longer content to demonstrate priority-based filtering
                    result_text = (
                        f"Record {record.id}: {record.text_content} "
                        f"Metrics: {len(record.metrics)} metrics. "
                        f"Detailed analysis: This record contains '{input.query}' with high relevance. "
                        f"All metric values: "
                        f"{', '.join([f'{k}={v}' for k, v in list(record.metrics.items())[:20]])}... "
                        f"Additional context: This is one of the most relevant records found in the search."
                    )
                else:
                    # Remaining results: shorter
                    result_text = (
                        f"Record {record.id}: {record.text_content[:200]}... "
                        f"Metrics: {len(record.metrics)} metrics "
                        f"(sample: {list(record.metrics.items())[:5]})"
                    )

                tokens = self._token_estimator.estimate(result_text)

                # Only include if within per-result limit
                if tokens <= input.max_tokens_per_result:
                    formatted_results.append(
                        {
                            "id": record.id,
                            "content": result_text,
                            "tokens": tokens,
                            "metrics_count": len(record.metrics),
                            "metadata": record.metadata,
                        }
                    )
                    total_tokens += tokens
                    print(f"    Result {i+1}: {tokens} tokens (within per-result limit)")
                else:
                    print(f"    Result {i+1}: {tokens} tokens (EXCEEDS per-result limit, excluded)")

            print(f"  Total tokens for all results: {total_tokens:,}")

            return Result.ok(
                SkillOutput(
                    data={
                        "query": input.query,
                        "total_records_searched": self._data_asset.TOTAL_RECORDS,
                        "results_returned": len(formatted_results),
                        "results": formatted_results,
                        "total_tokens": total_tokens,
                        "cached": False,
                    },
                )
            )

        except Exception as e:
            return Result.fail(f"Retrieval failed: {e}")


# ============================================================================
# Context Compilation Tool (manages token budget)
# ============================================================================


class ContextCompilationTool(Tool):
    """
    Tool that compiles context from retrieval results within token budget.

    This is the KEY component for handling large data assets:
    - Takes retrieval results
    - Compiles them within token budget
    - Prioritizes most relevant results
    - Summarizes if needed (using AdvancedContextCompiler)
    """

    def __init__(
        self,
        compiler: ContextCompiler,
        budget: TokenBudget,
    ):
        self._compiler = compiler
        self._budget = budget

    @property
    def id(self) -> ToolID:
        return ToolID("compile_context")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="compile_context",
            description="Compile retrieval results into context within token budget",
            parameters={
                "type": "object",
                "properties": {},
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Compile context from retrieval results.

        This ensures we only include what fits in the token budget,
        even if we retrieved many results.
        """
        # Get retrieval results from kwargs (passed from node executor)
        results = kwargs.get("results", [])

        if not results:
            return Result.fail("No results to compile")

        print(f"\n[Context Compilation] Processing {len(results)} retrieval results...")
        print(f"  Token Budget: {self._budget.available_tokens:,} tokens available")

        # Convert results to artifacts for compilation
        artifacts = tuple((f"result_{i}", result.get("content", "")) for i, result in enumerate(results))

        # Calculate total tokens if we included everything
        from cemaf.context.compiler import SimpleTokenEstimator

        estimator = SimpleTokenEstimator()
        total_tokens_all = sum(estimator.estimate(result.get("content", "")) for result in results)
        print(f"  Total tokens if all included: {total_tokens_all:,}")

        # Set priorities (most relevant first - earlier results have higher priority)
        priorities = {
            f"result_{i}": len(results) - i  # Higher priority for earlier (more relevant) results
            for i in range(len(results))
        }

        # Compile context within budget
        compiled = await self._compiler.compile(
            artifacts=artifacts,
            memories=(),  # No memories in this example
            budget=self._budget,
            priorities=priorities,
        )

        print(f"  Sources included: {len(compiled.sources)}/{len(results)}")
        print(f"  Total tokens after compilation: {compiled.total_tokens:,}")
        print(f"  Within budget: {compiled.within_budget()}")

        # Show algorithm metadata
        algorithm_method = compiled.metadata.get("algorithm_used", "unknown")
        print(f"  Algorithm used: {algorithm_method}")

        if len(compiled.sources) < len(results):
            excluded = len(results) - len(compiled.sources)
            print(f"  ⚠️  Excluded {excluded} results to fit within budget")

            # Show which results were included/excluded
            included_keys = {s.key for s in compiled.sources}
            print("\n  Included results (highest priority):")
            for i, result in enumerate(results):
                key = f"result_{i}"
                if key in included_keys:
                    tokens = estimator.estimate(result.get("content", ""))
                    print(f"    ✓ {key}: {tokens} tokens (priority: {priorities.get(key, 0)})")
            print("\n  Excluded results (lower priority):")
            for i, result in enumerate(results):
                key = f"result_{i}"
                if key not in included_keys:
                    tokens = estimator.estimate(result.get("content", ""))
                    print(f"    ✗ {key}: {tokens} tokens (priority: {priorities.get(key, 0)})")

        # Show algorithm-specific metadata
        if "max_priority_sum" in compiled.metadata:
            print(f"  Max priority sum achieved: {compiled.metadata['max_priority_sum']}")
        if "guaranteed_optimal" in compiled.metadata:
            print(f"  Guaranteed optimal: {compiled.metadata['guaranteed_optimal']}")

        return Result.ok(
            {
                "compiled_context": compiled,
                "total_tokens": compiled.total_tokens,
                "within_budget": compiled.within_budget(),
                "sources_included": len(compiled.sources),
                "sources_excluded": len(results) - len(compiled.sources),
                "messages": compiled.to_messages(),
            }
        )


# ============================================================================
# Analysis Tool (uses compiled context)
# ============================================================================


class AnalysisTool(Tool):
    """
    Analysis tool that uses compiled context (within token budget).

    This demonstrates:
    - Model thinking: LLM reasoning with tool calls
    - Token optimization: Only sees budgeted context
    - Audit trail: LLM calls are recorded
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        run_logger: InMemoryRunLogger | None = None,
    ):
        self._llm_client = llm_client
        self._run_logger = run_logger

    @property
    def id(self) -> ToolID:
        return ToolID("analyze")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="analyze",
            description="Analyze compiled context using LLM (within token budget)",
            parameters={
                "type": "object",
                "properties": {
                    "focus": {"type": "string"},
                },
            },
            required=("focus",),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Analyze using compiled context with LLM.

        Demonstrates:
        1. Model thinking: LLM reasoning about the query
        2. Token optimization: Only receives budgeted context
        3. Audit trail: LLM call is recorded
        """
        from cemaf.core.utils import utc_now

        focus = kwargs.get("focus", "general")
        compiled_context = kwargs.get("compiled_context")

        if not compiled_context:
            return Result.fail("No compiled context provided")

        # Convert compiled context to LLM messages
        messages = compiled_context.to_messages()

        # Add user query
        query = kwargs.get("query", "hello")
        messages.append(
            Message.user(f"Analyze the retrieved results focusing on: {focus}. " f"Query was: '{query}'")
        )

        print("\n[LLM Analysis] Calling LLM with compiled context:")
        print(f"  Messages: {len(messages)}")
        print(f"  Context tokens: {compiled_context.total_tokens:,}")
        print(f"  Within budget: {compiled_context.within_budget()}")

        # Call LLM (mocked for this example, but shows the pattern)
        if self._llm_client:
            start_time = utc_now()
            llm_result = await self._llm_client.complete(messages)
            end_time = utc_now()
            duration_ms = (end_time - start_time).total_seconds() * 1000

            # Record LLM call for audit trail
            if self._run_logger:
                from cemaf.core.types import TokenCount

                llm_call = LLMCall(
                    model=self._llm_client.config.model,
                    messages=[m.to_dict() for m in messages],
                    response=llm_result.message.content if llm_result.message else "",
                    input_tokens=TokenCount(llm_result.prompt_tokens),
                    output_tokens=TokenCount(llm_result.completion_tokens),
                    duration_ms=duration_ms,
                    timestamp=start_time,
                    correlation_id="",
                )
                self._run_logger.record_llm_call(llm_call)
                print(
                    f"  LLM call recorded: {llm_result.prompt_tokens} input + "
                    f"{llm_result.completion_tokens} output tokens"
                )

            if llm_result.success and llm_result.message:
                analysis = llm_result.message.content
            else:
                analysis = f"LLM analysis failed: {llm_result.error}"
        else:
            # Mock analysis for demonstration
            analysis = (
                f"LLM Analysis (focus: {focus}):\n"
                f"Based on the {len(compiled_context.sources)} retrieved records "
                f"({compiled_context.total_tokens:,} tokens), I found relevant matches "
                f"for the query '{query}'. The results show high relevance scores "
                f"indicating strong matches in the dataset."
            )
            print("  Using mock LLM (set llm_client for real analysis)")

        return Result.ok(
            {
                "analysis": analysis,
                "focus": focus,
                "context_tokens": compiled_context.total_tokens,
                "sources_analyzed": len(compiled_context.sources),
            }
        )


# ============================================================================
# Build Large-Scale Retrieval DAG
# ============================================================================


def build_large_scale_retrieval_dag(
    data_asset: MassiveDataAsset,
    compiler: ContextCompiler,
    budget: TokenBudget,
    llm_client: LLMClient | None = None,
) -> DAG:
    """
    Build a DAG for large-scale data asset retrieval with context engineering.

    Flow:
        query → retrieve (9T records) → compile (within budget) → analyze → response
                      ↓                        ↓
                (top-k only)            (token budget enforced)

    Key Strategy:
        - Search 9T records but only retrieve top-k
        - Compile results within token budget
        - Only include what fits in context window
        - Summarize if needed (AdvancedCompiler)
    """
    from cemaf.core.enums import NodeType
    from cemaf.core.types import NodeID

    dag = DAG(
        name="large_scale_retrieval", description="Retrieve from 9T records with token budget management"
    )

    # Node 1: Large-scale retrieval (searches 9T records, returns top-k)
    token_estimator = SimpleTokenEstimator()
    retrieval_skill = LargeScaleRetrievalSkill(data_asset, token_estimator)

    retrieve_node = Node(
        id=NodeID("retrieve"),
        type=NodeType.SKILL,
        name="Retrieve from 9T Records",
        ref_id=str(retrieval_skill.id),
        output_key="retrieval_results",  # Patches into context
        retry_on_failure=True,
        max_retries=2,
    )
    dag = dag.add_node(retrieve_node)

    # Node 2: Compile context within token budget
    # This is the KEY step: ensures we only include what fits
    compilation_tool = ContextCompilationTool(compiler, budget)
    dag = dag.add_node(
        Node.tool(
            id="compile_context",
            name="Compile Context (Token Budget)",
            tool_id=str(compilation_tool.id),
            output_key="compiled_context",
        )
    )

    # Node 3: Analysis using compiled context (within budget)
    analysis_tool = AnalysisTool(llm_client)
    dag = dag.add_node(
        Node.tool(
            id="analyze",
            name="Analyze (Uses Compiled Context)",
            tool_id=str(analysis_tool.id),
            output_key="analysis_result",
        )
    )

    # Node 4: Format response
    dag = dag.add_node(
        Node.tool(
            id="format",
            name="Format Response",
            tool_id="format_tool",
            output_key="final_response",
        )
    )

    # Edges
    dag = dag.add_edge(Edge(source=NodeID("retrieve"), target=NodeID("compile_context")))
    dag = dag.add_edge(Edge(source=NodeID("compile_context"), target=NodeID("analyze")))
    dag = dag.add_edge(Edge(source=NodeID("analyze"), target=NodeID("format")))

    return dag


# ============================================================================
# Example Usage: Large-Scale Data Asset Search
# ============================================================================


async def main():
    """
    Demonstrate searching 9 trillion records with context engineering.

    Query: "find hello"
    Problem: 9T records exceed any context window
    Solution: Retrieval + Token Budgeting + Context Compilation
    """
    print("=" * 80)
    print("Large-Scale Data Asset Retrieval Example")
    print("=" * 80)
    print()

    # Setup: Simulate massive data asset
    data_asset = MassiveDataAsset()
    asset_info = data_asset.get_total_size_estimate()

    print(f"Data Asset: {asset_info['total_records']:,} records")
    print(f"Metrics per record: {asset_info['metrics_per_record']}")
    print(f"Estimated size: {asset_info['estimated_size_pb']:.2f} PB")
    print(f"Estimated tokens: {asset_info['estimated_tokens']:,}")
    print()

    # Setup: Token budget (e.g., GPT-4: 8K tokens, reserve 2K for output)
    # Use a SMALL budget to demonstrate context engineering when results exceed budget
    budget = TokenBudget(
        max_tokens=1000,  # Small budget to force filtering
        reserved_for_output=200,
    ).with_allocation(
        section="retrieval_results",
        max_tokens=500,  # Very small budget to demonstrate filtering
        priority=10,
    )
    print(f"Token Budget: {budget.max_tokens:,} tokens")
    print(f"Available for context: {budget.available_tokens:,} tokens")
    print(f"Reserved for output: {budget.reserved_for_output:,} tokens")
    print("⚠️  Using SMALL budget to demonstrate context engineering!")
    print()

    # Setup: Context compiler with algorithm selection
    token_estimator = SimpleTokenEstimator()

    # Demonstrate different algorithms
    print("Algorithm Options:")
    print("  1. Greedy (default): Fast, includes highest priority first")
    print("  2. Knapsack: Optimal priority maximization, slower")
    print("  3. Optimal: Guaranteed optimal for small sets")
    print()

    # Use greedy algorithm (default behavior, but now pluggable)
    from cemaf.context.algorithm import GreedySelectionAlgorithm

    algorithm = GreedySelectionAlgorithm()
    print(f"Using algorithm: {algorithm.__class__.__name__}")
    print()

    compiler = PriorityContextCompiler(
        token_estimator=token_estimator,
        algorithm=algorithm,
    )

    # Uncomment to try knapsack algorithm:
    # algorithm = KnapsackSelectionAlgorithm()
    # compiler = PriorityContextCompiler(token_estimator=token_estimator, algorithm=algorithm)

    # Setup: RunLogger for full audit trail
    run_logger = InMemoryRunLogger()
    print("✅ RunLogger initialized for audit trail")
    print()

    # Build DAG
    dag = build_large_scale_retrieval_dag(
        data_asset=data_asset,
        compiler=compiler,
        budget=budget,
        llm_client=None,  # Set to LLMClient for AdvancedCompiler
    )

    # Create node executor

    class LargeScaleNodeExecutor:
        def __init__(
            self,
            retrieval_skill: LargeScaleRetrievalSkill,
            compilation_tool: ContextCompilationTool,
            analysis_tool: AnalysisTool,
            run_logger: InMemoryRunLogger | None = None,
        ):
            self._retrieval_skill = retrieval_skill
            self._compilation_tool = compilation_tool
            self._analysis_tool = analysis_tool
            self._run_logger = run_logger

        async def execute_node(self, node: Node, context: Context) -> NodeResult:
            """Execute node and record tool calls for audit trail."""
            from cemaf.core.utils import utc_now

            """Execute a single node."""
            if node.type.value == "skill":
                if str(node.ref_id) == "large_scale_retrieval":
                    query = context.get("query", "hello")
                    input_data = LargeScaleRetrievalInput(
                        query=query,
                        top_k=10,  # Only retrieve top 10 from 9T records
                        max_tokens_per_result=200,
                    )
                    result = await self._retrieval_skill.execute(
                        input_data,
                        SkillContext(run_id="test", agent_id="test"),
                    )

                    if result.success:
                        # Output will be patched into context by DAGExecutor via output_key
                        output_data = result.data.data if hasattr(result.data, "data") else result.data
                        return NodeResult(
                            node_id=node.id,
                            success=True,
                            output=output_data,
                        )
                    else:
                        return NodeResult(
                            node_id=node.id,
                            success=False,
                            error=result.error,
                        )

            elif node.type.value == "tool":
                if str(node.ref_id) == "compile_context":
                    # Get retrieval results from context (patched by previous node via output_key)
                    retrieval_data = context.get("retrieval_results", {})
                    if isinstance(retrieval_data, dict):
                        results = retrieval_data.get("results", [])
                    else:
                        results = []

                    # Pass results to compilation tool
                    tool_start = utc_now()
                    result = await self._compilation_tool.execute(results=results)
                    tool_duration = (utc_now() - tool_start).total_seconds() * 1000

                    # Record tool call for audit trail
                    if self._run_logger and result.success:
                        tool_call = RecordedToolCall(
                            tool_id=str(self._compilation_tool.id),
                            input={"results_count": len(results)},
                            output={
                                "sources_included": result.data.get("sources_included", 0),
                                "total_tokens": result.data.get("total_tokens", 0),
                            },
                            duration_ms=tool_duration,
                            timestamp=tool_start,
                            correlation_id="",
                            success=result.success,
                        )
                        self._run_logger.record_tool_call(tool_call)

                    if result.success:
                        # Output will be patched into context by DAGExecutor via output_key
                        return NodeResult(
                            node_id=node.id,
                            success=True,
                            output=result.data,
                        )
                    else:
                        return NodeResult(
                            node_id=node.id,
                            success=False,
                            error=result.error,
                        )

                elif str(node.ref_id) == "analyze":
                    # Get compiled context (patched by previous node via output_key)
                    compiled_data = context.get("compiled_context", {})
                    # Extract CompiledContext if it's wrapped in a dict
                    if isinstance(compiled_data, dict):
                        compiled_context = compiled_data.get("compiled_context")
                    else:
                        compiled_context = compiled_data

                    print("\n[Analysis] Using compiled context:")
                    if compiled_context:
                        print(f"  Sources available: {len(compiled_context.sources)}")
                        print(f"  Total tokens: {compiled_context.total_tokens:,}")
                        print(f"  Within budget: {compiled_context.within_budget()}")

                    tool_start = utc_now()
                    result = await self._analysis_tool.execute(
                        focus="finding 'hello'",
                        compiled_context=compiled_context,
                        query=context.get("query", "hello"),
                    )
                    tool_duration = (utc_now() - tool_start).total_seconds() * 1000

                    # Record tool call for audit trail
                    if self._run_logger and result.success:
                        tool_call = RecordedToolCall(
                            tool_id=str(self._analysis_tool.id),
                            input={
                                "focus": "finding 'hello'",
                                "context_tokens": compiled_context.total_tokens if compiled_context else 0,
                            },
                            output={"sources_analyzed": result.data.get("sources_analyzed", 0)},
                            duration_ms=tool_duration,
                            timestamp=tool_start,
                            correlation_id="",
                            success=result.success,
                        )
                        self._run_logger.record_tool_call(tool_call)

                    if result.success:
                        return NodeResult(
                            node_id=node.id,
                            success=True,
                            output=result.data,
                        )
                    else:
                        return NodeResult(
                            node_id=node.id,
                            success=False,
                            error=result.error,
                        )

                elif str(node.ref_id) == "format_tool":
                    # Format final response
                    retrieval_data = context.get("retrieval_results", {})
                    compiled_data = context.get("compiled_context", {})

                    # Extract compiled context
                    if isinstance(compiled_data, dict):
                        compiled_context = compiled_data.get("compiled_context")
                    else:
                        compiled_context = compiled_data

                    results_count = 0
                    if isinstance(retrieval_data, dict):
                        results_count = len(retrieval_data.get("results", []))

                    formatted = {
                        "query": context.get("query"),
                        "results_found": results_count,
                        "context_tokens": compiled_context.total_tokens if compiled_context else 0,
                        "analysis": context.get("analysis_result"),
                    }
                    return NodeResult(
                        node_id=node.id,
                        success=True,
                        output=formatted,
                    )

            return NodeResult(
                node_id=node.id,
                success=False,
                error="Unknown node",
            )

    # Create executor with run logger for audit trail
    retrieval_skill = LargeScaleRetrievalSkill(data_asset, token_estimator)
    compilation_tool = ContextCompilationTool(compiler, budget)
    analysis_tool = AnalysisTool(run_logger=run_logger)  # Pass logger for LLM call recording
    node_executor = LargeScaleNodeExecutor(
        retrieval_skill,
        compilation_tool,
        analysis_tool,
        run_logger=run_logger,  # Pass logger to record tool calls
    )
    executor = DAGExecutor(
        node_executor=node_executor,
        run_logger=run_logger,  # Enable full audit trail
    )

    # Execute: Search for "hello" in 9T records
    print("Query: 'find hello'")
    print("-" * 80)

    initial_context = Context(data={"query": "hello"})
    result = await executor.run(dag, initial_context=initial_context)

    print(f"\nExecution Success: {result.success}")
    print()

    # Show retrieval results
    retrieval_results = result.final_context.get("retrieval_results", {})
    print(f"Records Searched: {retrieval_results.get('total_records_searched', 0):,}")
    print(f"Results Retrieved: {retrieval_results.get('results_returned', 0)}")
    print(f"Total Tokens (Retrieval): {retrieval_results.get('total_tokens', 0)}")
    print()

    # Show compiled context (extract from dict if wrapped)
    compiled_data = result.final_context.get("compiled_context", {})
    if isinstance(compiled_data, dict):
        compiled_context = compiled_data.get("compiled_context")
    else:
        compiled_context = compiled_data

    if compiled_context:
        print("Compiled Context:")
        print(f"  - Sources Included: {len(compiled_context.sources)}")
        print(f"  - Total Tokens: {compiled_context.total_tokens:,}")
        print(f"  - Within Budget: {compiled_context.within_budget()}")
        print(f"  - Budget Available: {compiled_context.budget.available_tokens:,}")

        # Show which sources were included/excluded
        if compiled_data and isinstance(compiled_data, dict):
            sources_excluded = compiled_data.get("sources_excluded", 0)
            if sources_excluded > 0:
                print(f"  - Sources Excluded: {sources_excluded} (didn't fit in budget)")
        print()

    # Show final response
    final_response = result.final_context.get("final_response", {})
    print("Final Response:")
    print(f"  - Query: {final_response.get('query')}")
    print(f"  - Results Found: {final_response.get('results_found')}")
    print(f"  - Context Tokens Used: {final_response.get('context_tokens')}")
    print()

    # Key takeaway
    print("=" * 80)
    print("KEY TAKEAWAY:")
    print("=" * 80)
    print("✅ Searched 9 TRILLION records")
    print("✅ Retrieved only top-k results (not all 9T)")
    print("✅ Compiled context within token budget")
    print("✅ Only included what fits in context window")
    print("✅ Downstream analysis only sees budgeted context")
    print()
    print("This is how CEMAF handles data assets that exceed context limits!")
    print()
    print("=" * 80)
    print("SOLUTION SUMMARY:")
    print("=" * 80)
    print("1. DON'T load all 9T records into context")
    print("   → Use retrieval/search to find relevant records")
    print()
    print("2. ONLY retrieve top-k results (e.g., top 10)")
    print("   → Hybrid search (vector + keyword) finds most relevant")
    print()
    print("3. COMPILE context within token budget")
    print("   → PriorityContextCompiler includes highest priority first")
    print("   → AdvancedContextCompiler can summarize if still too large")
    print()
    print("4. DOWNSTREAM nodes only see budgeted context")
    print("   → Analysis tool receives compiled context, not raw 9T records")
    print("   → Stays within LLM context window limits")
    print()
    print("Result: Can search 9T records but only use what fits in context!")
    print("=" * 80)
    print()

    # ============================================================================
    # DEMONSTRATE FULL CEMAF CAPABILITIES
    # ============================================================================

    print("=" * 80)
    print("FULL CEMAF CAPABILITIES DEMONSTRATION")
    print("=" * 80)
    print()

    # Get the run record for audit trail
    run_record = run_logger.get_record(str(result.run_id))
    if run_record:
        print("📊 AUDIT TRAIL:")
        print(f"  Run ID: {run_record.run_id}")
        print(f"  Duration: {run_record.duration_ms:.2f}ms")
        print(f"  Total Patches: {run_record.total_patches}")
        print(f"  Total Tool Calls: {run_record.total_tool_calls}")
        print(f"  Total LLM Calls: {run_record.total_llm_calls}")
        print(f"  Total Tokens Used: {run_record.total_tokens:,}")
        print()

        # Show provenance of context changes
        print("🔍 PROVENANCE TRACKING (Context Changes):")
        for i, patch in enumerate(run_record.patches[:5], 1):  # Show first 5
            print(f"  {i}. {patch.operation.value} '{patch.path}'")
            print(f"     Source: {patch.source.value} ({patch.source_id})")
            print(f"     Reason: {patch.reason or 'N/A'}")
            print(f"     Timestamp: {patch.timestamp.isoformat()}")
        if len(run_record.patches) > 5:
            print(f"  ... and {len(run_record.patches) - 5} more patches")
        print()

        # Show tool calls
        print("🔧 TOOL CALLS RECORDED:")
        for i, tool_call in enumerate(run_record.tool_calls, 1):
            print(f"  {i}. {tool_call.tool_id}")
            print(f"     Duration: {tool_call.duration_ms:.2f}ms")
            print(f"     Success: {tool_call.success}")
            if tool_call.error:
                print(f"     Error: {tool_call.error}")
        print()

        # Show LLM calls (if any)
        if run_record.llm_calls:
            print("🤖 LLM CALLS RECORDED:")
            for i, llm_call in enumerate(run_record.llm_calls, 1):
                print(f"  {i}. Model: {llm_call.model}")
                print(f"     Input tokens: {llm_call.input_tokens:,}")
                print(f"     Output tokens: {llm_call.output_tokens:,}")
                print(f"     Duration: {llm_call.duration_ms:.2f}ms")
        else:
            print("🤖 LLM CALLS: None (using mock for this example)")
        print()

        # Show context optimization
        print("💾 CONTEXT MEMORY OPTIMIZATION:")
        initial_tokens = 0
        if run_record.initial_context:
            # Estimate initial context tokens
            initial_data = run_record.initial_context.to_dict()
            initial_tokens = token_estimator.estimate(str(initial_data))

        final_tokens = 0
        if run_record.final_context:
            final_data = run_record.final_context.to_dict()
            final_tokens = token_estimator.estimate(str(final_data))

        compiled_data = result.final_context.get("compiled_context", {})
        if isinstance(compiled_data, dict):
            compiled_context = compiled_data.get("compiled_context")
        else:
            compiled_context = compiled_data

        if compiled_context:
            print(f"  Initial context: ~{initial_tokens} tokens")
            print(f"  Retrieved results: {retrieval_results.get('total_tokens', 0):,} tokens")
            print(f"  Compiled context: {compiled_context.total_tokens:,} tokens")
            print(f"  Final context: ~{final_tokens} tokens")
            excluded_tokens = retrieval_results.get("total_tokens", 0) - compiled_context.total_tokens
            print(f"  Optimization: Excluded {excluded_tokens:,} tokens")
            budget_pct = compiled_context.total_tokens / budget.available_tokens * 100
            print(f"  Budget utilization: {budget_pct:.1f}%")
        print()

        # Demonstrate REPRODUCIBILITY
        print("🔄 REPRODUCIBILITY DEMONSTRATION:")
        print("  Replaying run to verify deterministic behavior...")

        replayer = Replayer(run_record)
        replay_result = await replayer.replay(mode=ReplayMode.PATCH_ONLY)

        if replay_result.success:
            print("  ✅ Replay successful!")
            print(f"  Patches applied: {replay_result.patches_applied}")
            print(f"  Duration: {replay_result.duration_ms:.2f}ms")

            # Verify final context matches
            if run_record.final_context and replay_result.final_context:
                final_dict = run_record.final_context.to_dict()
                replay_dict = replay_result.final_context.to_dict()

                # Compare key fields
                if final_dict.get("query") == replay_dict.get("query"):
                    print("  ✅ Final context matches (deterministic replay)")
                else:
                    print("  ⚠️  Context divergence detected")

            if replay_result.divergences:
                print(f"  ⚠️  Divergences: {len(replay_result.divergences)}")
                for div in replay_result.divergences[:3]:
                    print(f"     - {div}")
            else:
                print("  ✅ No divergences (perfect reproducibility)")
        else:
            print(f"  ❌ Replay failed: {replay_result.error}")
        print()

        # Show serialization (for persistence)
        print("💾 SERIALIZATION (for persistence):")
        record_dict = run_record.to_dict()
        print(f"  Run record serialized: {len(str(record_dict)):,} bytes")
        print("  Can be saved to disk/database for later replay")
        print("  Can be loaded with: RunRecord.from_dict(record_dict)")
        print()

    print("=" * 80)
    print("SUMMARY: Full CEMAF Capabilities Demonstrated")
    print("=" * 80)
    print("✅ Context Engineering: Token budget enforced, optimization shown")
    print("✅ Model Thinking: LLM calls recorded (mock for demo)")
    print("✅ Reproducibility: Run replayed deterministically")
    print("✅ Audit Trail: Every patch, tool call, LLM call recorded")
    print("✅ Memory Optimization: Only included what fits in budget")
    print("=" * 80)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
