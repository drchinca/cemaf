"""Tests for context compiler integration with ContextNodeExecutor."""

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import (
    CompiledContext,
    PriorityContextCompiler,
    SimpleTokenEstimator,
)
from cemaf.context.context import Context
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import Node
from cemaf.retrieval.factories import create_in_memory_vector_store


@pytest.fixture
def registry() -> AgentRegistry:
    """Create a registry with built-in agents available."""
    return AgentRegistry()


@pytest.fixture
def compiler() -> PriorityContextCompiler:
    """Create a real PriorityContextCompiler with SimpleTokenEstimator."""
    return PriorityContextCompiler(
        token_estimator=SimpleTokenEstimator(chars_per_token=4.0),
    )


@pytest.fixture
def token_budget() -> TokenBudget:
    """Create a token budget with generous limits for testing."""
    return TokenBudget(max_tokens=4000, reserved_for_output=500)


@pytest.fixture
def librarian_node() -> Node:
    """Create a Librarian agent node."""
    return Node(
        id=NodeID("step_1"),
        type=NodeType.AGENT,
        name="Librarian",
        ref_id="Librarian",
    )


class TestExecutorWithoutCompiler:
    """Backward compatibility: executor works without compiler."""

    @pytest.mark.asyncio
    async def test_executor_without_compiler_works(
        self,
        registry: AgentRegistry,
        librarian_node: Node,
    ) -> None:
        """Executor without compiler produces no artifacts."""
        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Librarian", vector_store=vector_store)
        assert agent is not None
        registry.register_agent(agent_instance=agent)

        executor = ContextNodeExecutor(agent_registry=registry)

        context = Context(
            data={"_resolved_inputs": {"intent_query": "test query"}},
        )
        result = await executor.execute_node(
            node=librarian_node,
            context=context,
        )
        assert result.success
        assert result.output is not None


class TestExecutorWithCompiler:
    """Compiler wiring populates AgentContext.artifacts."""

    @pytest.mark.asyncio
    async def test_executor_with_compiler_populates_artifacts(
        self,
        registry: AgentRegistry,
        compiler: PriorityContextCompiler,
        token_budget: TokenBudget,
        librarian_node: Node,
    ) -> None:
        """Compiled context appears in AgentContext.artifacts when compiler is provided."""
        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Librarian", vector_store=vector_store)
        assert agent is not None
        registry.register_agent(agent_instance=agent)

        executor = ContextNodeExecutor(
            agent_registry=registry,
            context_compiler=compiler,
            token_budget=token_budget,
        )

        context = Context(
            data={
                "_resolved_inputs": {
                    "intent_query": "professional audit style",
                },
            },
        )
        result = await executor.execute_node(
            node=librarian_node,
            context=context,
        )
        assert result.success
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_compile_context_builds_sources_from_inputs(
        self,
        registry: AgentRegistry,
        compiler: PriorityContextCompiler,
        token_budget: TokenBudget,
    ) -> None:
        """_compile_context converts dict inputs into artifact pairs."""
        executor = ContextNodeExecutor(
            agent_registry=registry,
            context_compiler=compiler,
            token_budget=token_budget,
        )

        compiled = await executor._compile_context(
            agent_name="test_agent",
            inputs={"key1": "value1", "key2": "value2"},
            memories={"mem_key": "mem_value"},
        )
        assert compiled is not None
        assert compiled.total_tokens > 0

        source_keys = [s.key for s in compiled.sources]
        assert "key1" in source_keys
        assert "key2" in source_keys
        assert "memory:mem_key" in source_keys

    @pytest.mark.asyncio
    async def test_compile_context_without_compiler_returns_none(
        self,
        registry: AgentRegistry,
    ) -> None:
        """_compile_context returns None when compiler is not configured."""
        executor = ContextNodeExecutor(agent_registry=registry)

        compiled = await executor._compile_context(
            agent_name="test_agent",
            inputs={"key1": "value1"},
            memories={},
        )
        assert compiled is None


class TestCompilationFailureGraceful:
    """Compiler failures must not break agent execution."""

    @pytest.mark.asyncio
    async def test_compilation_failure_is_graceful(
        self,
        registry: AgentRegistry,
        token_budget: TokenBudget,
        librarian_node: Node,
    ) -> None:
        """Agent still runs when compiler raises an exception."""
        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Librarian", vector_store=vector_store)
        assert agent is not None
        registry.register_agent(agent_instance=agent)

        class FailingCompiler:
            """Compiler that always raises."""

            async def compile(
                self,
                artifacts: tuple[tuple[str, str], ...],
                memories: tuple[tuple[str, str], ...],
                budget: TokenBudget,
                priorities: dict[str, int] | None = None,
            ) -> CompiledContext:
                raise RuntimeError("Compilation exploded")

        executor = ContextNodeExecutor(
            agent_registry=registry,
            context_compiler=FailingCompiler(),  # type: ignore[arg-type]
            token_budget=token_budget,
        )

        context = Context(
            data={"_resolved_inputs": {"intent_query": "test query"}},
        )
        result = await executor.execute_node(
            node=librarian_node,
            context=context,
        )
        assert result.success
        assert result.output is not None


class TestCompiledContextRespectsBudget:
    """Token budget enforcement through the compilation pipeline."""

    @pytest.mark.asyncio
    async def test_compiled_context_respects_budget(
        self,
        registry: AgentRegistry,
        compiler: PriorityContextCompiler,
    ) -> None:
        """Compiled context total tokens stays within budget available_tokens."""
        tight_budget = TokenBudget(max_tokens=100, reserved_for_output=50)

        executor = ContextNodeExecutor(
            agent_registry=registry,
            context_compiler=compiler,
            token_budget=tight_budget,
        )

        # Feed large inputs that exceed the budget
        large_value = "x" * 1000
        compiled = await executor._compile_context(
            agent_name="test_agent",
            inputs={
                "big_input": large_value,
                "another_big": large_value,
            },
            memories={"big_mem": large_value},
        )
        assert compiled is not None
        assert compiled.total_tokens <= tight_budget.available_tokens

    @pytest.mark.asyncio
    async def test_compiled_context_includes_all_when_budget_allows(
        self,
        registry: AgentRegistry,
        compiler: PriorityContextCompiler,
    ) -> None:
        """All sources included when budget is generous."""
        generous_budget = TokenBudget(
            max_tokens=100_000,
            reserved_for_output=1_000,
        )

        executor = ContextNodeExecutor(
            agent_registry=registry,
            context_compiler=compiler,
            token_budget=generous_budget,
        )

        compiled = await executor._compile_context(
            agent_name="test_agent",
            inputs={"a": "small", "b": "tiny"},
            memories={"m1": "brief"},
        )
        assert compiled is not None
        assert len(compiled.sources) == 3
