"""
CEMAF Test Fixtures - Centralized, reusable test infrastructure.

Principles:
- DRY: Define once, use everywhere
- KISS: Simple fixtures, clear naming
- Readability: Descriptive names, docstrings
- Isolation: Each test gets fresh instances

Usage:
    def test_something(mock_llm, memory_store, sample_project):
        result = await mock_llm.complete([Message.user("Hi")])
        assert result.success
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from cemaf.core.enums import (
    ContextArtifactType,
    MemoryScope,
    RunStatus,
)

# =============================================================================
# Core Types & Enums
# =============================================================================
from cemaf.core.types import (
    AgentID,
    Confidence,
    NodeID,
    ProjectID,
    RunID,
    SkillID,
    ToolID,
)

# =============================================================================
# ID FIXTURES - Consistent test identifiers
# =============================================================================


@pytest.fixture
def agent_id() -> AgentID:
    """Standard test agent ID."""
    return AgentID("test-agent")


@pytest.fixture
def tool_id() -> ToolID:
    """Standard test tool ID."""
    return ToolID("test-tool")


@pytest.fixture
def skill_id() -> SkillID:
    """Standard test skill ID."""
    return SkillID("test-skill")


@pytest.fixture
def node_id() -> NodeID:
    """Standard test node ID."""
    return NodeID("test-node")


@pytest.fixture
def project_id() -> ProjectID:
    """Standard test project ID."""
    return ProjectID("test-project")


@pytest.fixture
def run_id() -> RunID:
    """Standard test run ID."""
    return RunID("test-run")


# =============================================================================
# TOOL FIXTURES
# =============================================================================

from cemaf.tools.base import Tool, ToolResult, ToolSchema


class MockTool(Tool):
    """Configurable mock tool for testing."""

    def __init__(
        self,
        tool_id: str = "mock-tool",
        name: str = "Mock Tool",
        result: ToolResult | None = None,
        side_effect: Exception | None = None,
    ):
        self._id = ToolID(tool_id)
        self._name = name
        self._result = result if result is not None else ToolResult.ok("mock result")
        self._side_effect = side_effect
        self.call_count = 0
        self.call_args: list[dict] = []

    @property
    def id(self) -> ToolID:
        return self._id

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description=f"Mock tool: {self._name}",
            parameters={"type": "object", "properties": {"input": {"type": "string"}}},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.call_count += 1
        self.call_args.append(kwargs)
        if self._side_effect:
            raise self._side_effect
        return self._result


@pytest.fixture
def mock_tool() -> MockTool:
    """Basic mock tool that succeeds."""
    return MockTool()


@pytest.fixture
def failing_tool() -> MockTool:
    """Mock tool that always fails."""
    return MockTool(
        tool_id="failing-tool",
        name="Failing Tool",
        result=ToolResult.fail("Intentional failure"),
    )


@pytest.fixture
def raising_tool() -> MockTool:
    """Mock tool that raises an exception."""
    return MockTool(
        tool_id="raising-tool",
        name="Raising Tool",
        side_effect=ValueError("Intentional exception"),
    )


# =============================================================================
# LLM FIXTURES
# =============================================================================

from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import (
    LLMConfig,
    Message,
    ToolCall,
)


@pytest.fixture
def llm_config() -> LLMConfig:
    """Standard LLM configuration for tests."""
    return LLMConfig(
        model="test-model",
        temperature=0.0,  # Deterministic for tests
        max_tokens=1000,
    )


@pytest.fixture
def mock_llm(llm_config: LLMConfig) -> MockLLMClient:
    """Mock LLM client with default responses."""
    return MockLLMClient(
        responses=["Test response"],
        config=llm_config,
    )


@pytest.fixture
def mock_llm_with_tools() -> MockLLMClient:
    """Mock LLM that returns tool calls."""
    tool_call = ToolCall(id="call_1", name="test_tool", arguments={"query": "test"})
    return MockLLMClient(
        responses=["Using tool..."],
        tool_calls=[[tool_call]],
    )


@pytest.fixture
def system_message() -> Message:
    """Standard system message."""
    return Message.system("You are a helpful assistant.")


@pytest.fixture
def user_message() -> Message:
    """Standard user message."""
    return Message.user("Hello!")


@pytest.fixture
def conversation() -> list[Message]:
    """Standard conversation for testing."""
    return [
        Message.system("You are a helpful assistant."),
        Message.user("Hello!"),
        Message.assistant("Hi there! How can I help?"),
        Message.user("What's 2+2?"),
    ]


# =============================================================================
# MEMORY FIXTURES
# =============================================================================

from cemaf.memory.base import InMemoryStore, MemoryItem


@pytest.fixture
def memory_store() -> InMemoryStore:
    """Fresh in-memory store for each test."""
    return InMemoryStore()


@pytest.fixture
def sample_memory_item() -> MemoryItem:
    """Sample memory item."""
    return MemoryItem(
        scope=MemoryScope.PROJECT,
        key="test-key",
        value={"data": "test-value"},
        confidence=Confidence(0.9),
    )


@pytest.fixture
async def populated_memory_store(memory_store: InMemoryStore) -> InMemoryStore:
    """Memory store with pre-populated data."""
    items = [
        MemoryItem(scope=MemoryScope.BRAND, key="brand-1", value={"name": "Test Brand"}),
        MemoryItem(scope=MemoryScope.PROJECT, key="proj-1", value={"status": "active"}),
        MemoryItem(scope=MemoryScope.SESSION, key="sess-1", value={"user": "alice"}),
    ]
    for item in items:
        await memory_store.set(item)
    return memory_store


# =============================================================================
# RETRIEVAL FIXTURES
# =============================================================================

from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import Document


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    """Mock embedding provider."""
    return MockEmbeddingProvider(dimension=128)


@pytest.fixture
def vector_store(embedding_provider: MockEmbeddingProvider) -> InMemoryVectorStore:
    """Fresh vector store for each test."""
    return InMemoryVectorStore(embedding_provider=embedding_provider)


@pytest.fixture
def sample_document() -> Document:
    """Sample document for testing."""
    return Document(
        id="doc-1",
        content="This is a test document about machine learning.",
        metadata={"type": "article", "author": "test"},
    )


@pytest.fixture
def sample_documents() -> list[Document]:
    """List of sample documents."""
    return [
        Document(id="1", content="The quick brown fox jumps over the lazy dog."),
        Document(id="2", content="Machine learning is a subset of artificial intelligence."),
        Document(id="3", content="Python is a popular programming language."),
        Document(id="4", content="Deep learning uses neural networks with many layers."),
    ]


@pytest.fixture
async def populated_vector_store(
    vector_store: InMemoryVectorStore,
    sample_documents: list[Document],
) -> InMemoryVectorStore:
    """Vector store with pre-indexed documents."""
    await vector_store.add_batch(sample_documents)
    return vector_store


# =============================================================================
# PERSISTENCE FIXTURES
# =============================================================================

from cemaf.persistence.entities import (
    ContextArtifact,
    Project,
    ProjectStatus,
    Run,
)


@pytest.fixture
def sample_project(project_id: ProjectID) -> Project:
    """Sample project entity (in DRAFT status - typical starting state)."""
    return Project(
        id=project_id,
        name="Test Project",
        description="A test project for unit tests",
        status=ProjectStatus.DRAFT,
    )


@pytest.fixture
def active_project(project_id: ProjectID) -> Project:
    """Sample project in ACTIVE status."""
    return Project(
        id=project_id,
        name="Active Test Project",
        description="An active test project",
        status=ProjectStatus.ACTIVE,
    )


@pytest.fixture
def sample_artifact(project_id: ProjectID) -> ContextArtifact:
    """Sample context artifact."""
    return ContextArtifact(
        project_id=project_id,
        type=ContextArtifactType.BRAND_CONSTITUTION,
        content="Brand values: Quality, Innovation, Trust",
        version=1,
        sha="abc123",
    )


@pytest.fixture
def sample_run(project_id: ProjectID, run_id: RunID) -> Run:
    """Sample run entity."""
    return Run(
        id=run_id,
        project_id=project_id,
        pipeline="test-pipeline",
        inputs={"query": "test"},
        status=RunStatus.PENDING,
    )


# =============================================================================
# DAG FIXTURES
# =============================================================================

from cemaf.orchestration.dag import DAG, Edge, Node


@pytest.fixture
def simple_dag() -> DAG:
    """Simple linear DAG: A → B → C."""
    dag = DAG(name="simple-dag", description="Test DAG")
    dag = dag.add_node(Node.tool(id="a", name="Step A", tool_id="tool_a", output_key="a_out"))
    dag = dag.add_node(Node.tool(id="b", name="Step B", tool_id="tool_b", output_key="b_out"))
    dag = dag.add_node(Node.tool(id="c", name="Step C", tool_id="tool_c", output_key="c_out"))
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
    dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("c")))
    return dag


@pytest.fixture
def diamond_dag() -> DAG:
    """Diamond DAG: A → (B, C) → D."""
    dag = DAG(name="diamond-dag")
    dag = dag.add_node(Node.tool(id="a", name="A", tool_id="t"))
    dag = dag.add_node(Node.tool(id="b", name="B", tool_id="t"))
    dag = dag.add_node(Node.tool(id="c", name="C", tool_id="t"))
    dag = dag.add_node(Node.tool(id="d", name="D", tool_id="t"))
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("b")))
    dag = dag.add_edge(Edge(source=NodeID("a"), target=NodeID("c")))
    dag = dag.add_edge(Edge(source=NodeID("b"), target=NodeID("d")))
    dag = dag.add_edge(Edge(source=NodeID("c"), target=NodeID("d")))
    return dag


# =============================================================================
# EXECUTOR FIXTURES
# =============================================================================

from cemaf.context.context import Context  # New import
from cemaf.orchestration.executor import DAGExecutor, NodeResult


class MockNodeExecutor:
    """Mock node executor for testing DAG execution."""

    def __init__(
        self,
        default_result: Any = "success",
        node_results: dict[str, NodeResult] | None = None,
        fail_nodes: set[str] | None = None,
    ):
        self.default_result = default_result
        self.node_results = node_results or {}
        self.fail_nodes = fail_nodes or set()
        self.executed: list[str] = []
        self.execution_order: list[str] = []

    async def execute_node(self, node: Node, context: Context) -> NodeResult:  # Updated to Context
        """Execute a node and record it."""
        self.executed.append(node.id)
        self.execution_order.append(node.id)

        if node.id in self.node_results:
            return self.node_results[node.id]

        if node.id in self.fail_nodes:
            return NodeResult(node_id=node.id, success=False, error="Intentional failure")

        return NodeResult(
            node_id=node.id,
            success=True,
            output=f"{self.default_result}_{node.id}",
        )

    def reset(self) -> None:
        """Reset execution tracking."""
        self.executed.clear()
        self.execution_order.clear()


@pytest.fixture
def mock_node_executor() -> MockNodeExecutor:
    """Mock node executor."""
    return MockNodeExecutor()


@pytest.fixture
def dag_executor(mock_node_executor: MockNodeExecutor) -> DAGExecutor:
    """DAG executor with mock node executor."""
    return DAGExecutor(node_executor=mock_node_executor)


# =============================================================================
# CHECKPOINTING FIXTURES
# =============================================================================

from cemaf.orchestration.checkpointer import (
    DAGCheckpoint,
    InMemoryCheckpointer,
)


@pytest.fixture
def checkpointer() -> InMemoryCheckpointer:
    """In-memory checkpointer for testing."""
    return InMemoryCheckpointer()


@pytest.fixture
def sample_checkpoint(run_id: RunID) -> DAGCheckpoint:
    """Sample checkpoint."""
    return DAGCheckpoint(
        run_id=run_id,
        dag_name="test-dag",
        status=RunStatus.RUNNING,
        completed_nodes=(NodeID("a"), NodeID("b")),
        pending_nodes=(NodeID("c"),),
        context={"a_out": "result_a", "b_out": "result_b"},
    )


# =============================================================================
# EVAL FIXTURES
# =============================================================================

from cemaf.evals.composite import CompositeEvaluator, EvalCase, EvalSuite
from cemaf.evals.evaluators import (
    ExactMatchEvaluator,
    LengthEvaluator,
)
from cemaf.evals.protocols import EvalConfig


@pytest.fixture
def eval_config() -> EvalConfig:
    """Standard eval configuration."""
    return EvalConfig(
        pass_threshold=0.5,
        fail_fast=False,
        include_reasoning=True,
    )


@pytest.fixture
def exact_match_evaluator() -> ExactMatchEvaluator:
    """Exact match evaluator."""
    return ExactMatchEvaluator()


@pytest.fixture
def length_evaluator() -> LengthEvaluator:
    """Length evaluator (10-100 chars)."""
    return LengthEvaluator(min_length=10, max_length=100)


@pytest.fixture
def composite_evaluator(
    exact_match_evaluator: ExactMatchEvaluator,
    length_evaluator: LengthEvaluator,
) -> CompositeEvaluator:
    """Composite evaluator with multiple checks."""
    return CompositeEvaluator([exact_match_evaluator, length_evaluator])


@pytest.fixture
def eval_suite() -> EvalSuite:
    """Eval suite with sample cases."""
    suite = EvalSuite(
        name="test-suite",
        evaluators=[ExactMatchEvaluator(), LengthEvaluator(min_length=1)],
    )
    suite.add_cases(
        [
            EvalCase(name="simple", output="hello", expected="hello"),
            EvalCase(name="mismatch", output="hi", expected="hello"),
        ]
    )
    return suite


# =============================================================================
# RESILIENCE FIXTURES
# =============================================================================

from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter
from cemaf.resilience.retry import BackoffStrategy, RetryConfig, RetryPolicy


@pytest.fixture
def retry_config() -> RetryConfig:
    """Fast retry config for tests."""
    return RetryConfig(
        max_attempts=3,
        initial_delay_seconds=0.01,  # Fast for tests
        max_delay_seconds=0.1,
        backoff_strategy=BackoffStrategy.EXPONENTIAL,
        jitter=False,  # Deterministic for tests
    )


@pytest.fixture
def retry_policy(retry_config: RetryConfig) -> RetryPolicy:
    """Retry policy for testing."""
    return RetryPolicy(retry_config)


@pytest.fixture
def circuit_config() -> CircuitConfig:
    """Fast circuit breaker config for tests."""
    return CircuitConfig(
        failure_threshold=3,
        recovery_timeout_seconds=0.01,  # Fast for tests
        success_threshold=2,
    )


@pytest.fixture
def circuit_breaker(circuit_config: CircuitConfig) -> CircuitBreaker:
    """Circuit breaker for testing."""
    return CircuitBreaker(circuit_config)


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """Rate limiter for testing."""
    return RateLimiter(RateLimitConfig(rate=100, burst=10))  # Fast for tests


# =============================================================================
# STREAMING FIXTURES
# =============================================================================

from cemaf.streaming.protocols import StreamBuffer, StreamEvent


@pytest.fixture
def stream_buffer() -> StreamBuffer:
    """Fresh stream buffer."""
    return StreamBuffer()


@pytest.fixture
def sample_stream_events() -> list[StreamEvent]:
    """Sample stream events."""
    return [
        StreamEvent.content("Hello "),
        StreamEvent.content("world"),
        StreamEvent.content("!"),
        StreamEvent.done("Hello world!"),
    ]


# =============================================================================
# OBSERVABILITY FIXTURES
# =============================================================================

from cemaf.observability.simple import NoOpMetrics, NoOpTracer, SimpleLogger


@pytest.fixture
def logger() -> SimpleLogger:
    """Simple logger for tests."""
    return SimpleLogger(name="test", level=40)  # ERROR level to reduce noise


@pytest.fixture
def tracer() -> NoOpTracer:
    """No-op tracer for tests."""
    return NoOpTracer()


@pytest.fixture
def metrics() -> NoOpMetrics:
    """No-op metrics for tests."""
    return NoOpMetrics()


# =============================================================================
# ASYNC HELPERS
# =============================================================================


@pytest.fixture
def async_success():
    """Async function that succeeds."""

    async def _success(*args, **kwargs):
        return "success"

    return _success


@pytest.fixture
def async_failure():
    """Async function that always fails."""

    async def _failure(*args, **kwargs):
        raise ValueError("Intentional failure")

    return _failure


@pytest.fixture
def async_flaky():
    """Async function that fails N times then succeeds."""
    call_count = {"count": 0}

    async def _flaky(fail_times: int = 2):
        call_count["count"] += 1
        if call_count["count"] <= fail_times:
            raise ValueError(f"Failure {call_count['count']}")
        return "success"

    _flaky.call_count = call_count
    return _flaky


# =============================================================================
# PATCH HELPERS
# =============================================================================


@pytest.fixture
def patch_datetime():
    """Fixture to patch datetime.now() for deterministic tests."""
    fixed_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    with patch("datetime.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        yield fixed_time


@pytest.fixture
def patch_uuid():
    """Fixture to patch uuid4 for deterministic IDs."""
    with patch("uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "test1234567890ab"
        mock_uuid.return_value.__str__ = lambda _: "test-uuid-1234"
        yield mock_uuid


# =============================================================================
# CONTEXT FIXTURES
# =============================================================================

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator


@pytest.fixture
def token_estimator() -> SimpleTokenEstimator:
    """Token estimator for tests."""
    return SimpleTokenEstimator()


@pytest.fixture
def token_budget() -> TokenBudget:
    """Standard token budget for tests."""
    return TokenBudget(max_tokens=4000, reserved_for_output=1000)


@pytest.fixture
def context_compiler(token_estimator: SimpleTokenEstimator) -> PriorityContextCompiler:
    """Context compiler for tests."""
    return PriorityContextCompiler(token_estimator)
