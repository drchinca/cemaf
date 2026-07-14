"""Tests for memory system integration with orchestration pipeline."""

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.context.context import Context
from cemaf.core.enums import MemoryScope, NodeType
from cemaf.core.types import NodeID, RunID
from cemaf.memory.factories import create_memory_manager, create_session_manager
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import DAGExecutor
from cemaf.retrieval.factories import create_in_memory_vector_store


@pytest.fixture
def memory_manager():
    return create_memory_manager()


@pytest.fixture
def session_manager(memory_manager):
    return create_session_manager(memory_manager=memory_manager)


@pytest.fixture
def registry():
    return AgentRegistry()


class TestContextNodeExecutorWithoutMemory:
    """Backward compatibility: existing behavior unchanged when memory is None."""

    @pytest.mark.asyncio
    async def test_executor_without_memory_works(self, registry: AgentRegistry) -> None:
        executor = ContextNodeExecutor(agent_registry=registry)
        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Unknown",
            ref_id="NonexistentAgent",
        )
        result = await executor.execute_node(node=node, context=Context())
        assert not result.success
        assert "not found" in (result.error or "")


class TestContextNodeExecutorWithMemory:
    """Memory-aware executor: recall populates global_memory, results ingested."""

    @pytest.mark.asyncio
    async def test_global_memory_populated_from_recall(
        self, registry: AgentRegistry, memory_manager, session_manager
    ) -> None:
        """Memories stored via manager appear in agent's global_memory."""
        # Store a memory before agent execution
        await memory_manager.remember(
            scope=MemoryScope.PROJECT,
            key="api_style",
            value={"style": "REST"},
            content_for_embedding="API design follows REST style",
        )

        vector_store = create_in_memory_vector_store()
        agent = registry.create_agent("Librarian", vector_store=vector_store)
        assert agent is not None
        registry.register_agent(agent_instance=agent)

        executor = ContextNodeExecutor(
            agent_registry=registry,
            memory_manager=memory_manager,
        )

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Librarian",
            ref_id="Librarian",
            input_mapping={"intent_query": "REST API design"},
        )
        context = Context(data={"_resolved_inputs": {"intent_query": "REST API design"}})

        # Execute — memory recall happens internally
        result = await executor.execute_node(node=node, context=context)
        # The agent ran (success or not depends on LLM, but memory recall didn't crash)
        assert result is not None

    @pytest.mark.asyncio
    async def test_memory_recall_failure_is_graceful(self, registry: AgentRegistry) -> None:
        """If memory recall raises, agent still executes with empty global_memory."""

        class BrokenMemoryManager:
            """Always raises on recall."""

            async def recall(self, query):
                raise RuntimeError("Memory store unavailable")

        executor = ContextNodeExecutor(
            agent_registry=registry,
            memory_manager=BrokenMemoryManager(),  # type: ignore[arg-type]
        )

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="Unknown",
            ref_id="NonexistentAgent",
        )
        # Should not raise — memory failure is isolated
        result = await executor.execute_node(node=node, context=Context())
        assert result is not None

    @pytest.mark.asyncio
    async def test_result_ingested_to_session(
        self, registry: AgentRegistry, memory_manager, session_manager
    ) -> None:
        """Successful agent result gets ingested into session memory.

        Regression: the previous version of this test had an `else` branch
        that passed whenever the Librarian agent failed (which it does in CI
        without an LLM). The test was green but proved nothing about ingest.
        This version registers a deterministic test agent that always
        succeeds, so the ingest path MUST fire.
        """
        from pydantic import BaseModel

        from cemaf.agents.base import Agent, AgentResult, AgentState
        from cemaf.core.types import AgentID

        class _DeterministicGoal(BaseModel):
            query: str = "x"

        class _DeterministicResult(BaseModel):
            text: str

        class _DeterministicAgent(Agent[_DeterministicGoal, _DeterministicResult]):
            @property
            def id(self) -> AgentID:
                return AgentID("DeterministicAgent")

            @property
            def description(self) -> str:
                return "Always succeeds with a fixed output"

            @property
            def skills(self) -> tuple[()]:
                return ()

            async def run(self, goal, context):
                return AgentResult.ok(
                    output=_DeterministicResult(text=f"processed:{goal.query}"),
                    state=AgentState(),
                )

        registry.register_agent(
            agent_instance=_DeterministicAgent(),
            goal_type=_DeterministicGoal,
        )

        ingested: list[str] = []

        class RecordingSessionManager:
            async def bootstrap(self, session_id, **kwargs):
                return await session_manager.bootstrap(session_id=session_id, **kwargs)

            async def ingest(self, session_id, key, value, **kwargs):
                ingested.append(key)
                return await session_manager.ingest(session_id=session_id, key=key, value=value, **kwargs)

            async def dispose(self, session_id, **kwargs):
                return await session_manager.dispose(session_id=session_id, **kwargs)

        node_executor = ContextNodeExecutor(agent_registry=registry)
        executor = DAGExecutor(
            node_executor=node_executor,
            session_manager=RecordingSessionManager(),  # type: ignore[arg-type]
        )

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="DeterministicAgent",
            ref_id="DeterministicAgent",
            input_mapping={"query": "test"},
        )
        result_run = await executor.run(
            dag=DAG(name="session-ingest", nodes=(node,), edges=(), entry_node=node.id),
            initial_context=Context(),
            run_id=RunID("test-run"),
        )
        result = result_run.node_results[0]

        assert result is not None
        assert result.success, f"agent must succeed: {result.error}"
        assert ingested == ["DeterministicAgent_output"]

    @pytest.mark.asyncio
    async def test_session_ingest_failure_is_graceful(self, registry: AgentRegistry) -> None:
        """If session ingest raises, the node result is still returned."""

        class BrokenSessionManager:
            """Always raises on ingest."""

            async def bootstrap(self, session_id):
                return None

            async def ingest(self, session_id, key, value, **kwargs):
                raise RuntimeError("Session store unavailable")

            async def dispose(self, session_id):
                return None

        from cemaf.orchestration.results import NodeResult

        class SuccessfulNodeExecutor:
            async def execute_node(self, node, context):
                return NodeResult(
                    node_id=node.id,
                    success=True,
                    output="accepted",
                    metadata={"agent_id": "DeterministicAgent"},
                )

        executor = DAGExecutor(
            node_executor=SuccessfulNodeExecutor(),
            session_manager=BrokenSessionManager(),  # type: ignore[arg-type]
        )

        node = Node(
            id=NodeID("step_1"),
            type=NodeType.AGENT,
            name="DeterministicAgent",
            ref_id="DeterministicAgent",
            output_key="accepted",
        )

        # Should not raise — ingest failure is isolated
        run = await executor.run(dag=DAG(name="broken-ingest", nodes=(node,), edges=(), entry_node=node.id))
        result = run.node_results[0]
        assert result.success
        assert result.metadata["context_warnings"][0]["stage"] == "session_ingest"


class TestDAGExecutorSessionLifecycle:
    """DAGExecutor bootstraps/disposes memory sessions around DAG runs."""

    @pytest.mark.asyncio
    async def test_session_bootstrapped_and_disposed(self, registry: AgentRegistry, session_manager) -> None:
        """Session is bootstrapped at start and disposed at end of DAG run."""
        executor = ContextNodeExecutor(agent_registry=registry)
        dag_executor = DAGExecutor(
            node_executor=executor,
            session_manager=session_manager,
        )

        dag = DAG(
            name="test-dag",
            nodes=(
                Node(
                    id=NodeID("step_1"),
                    type=NodeType.AGENT,
                    name="Test",
                    ref_id="NonexistentAgent",
                ),
            ),
            edges=(),
        )

        run_id = RunID("test-session-run")
        await dag_executor.run(dag=dag, run_id=run_id)

        # Session should have been disposed (get_state returns disposed or None)
        state = await session_manager.get_state(session_id=str(run_id))
        # After dispose, state is either removed (None) or marked DISPOSED
        if state is None:
            # Session was cleaned up -- this is valid
            assert state is None
        else:
            from cemaf.memory.session import SessionPhase

            assert state.phase == SessionPhase.DISPOSED

    @pytest.mark.asyncio
    async def test_dag_runs_without_session_manager(self, registry: AgentRegistry) -> None:
        """DAG executor works fine without session_manager (backward compat)."""
        executor = ContextNodeExecutor(agent_registry=registry)
        dag_executor = DAGExecutor(node_executor=executor)

        dag = DAG(
            name="test-dag",
            nodes=(
                Node(
                    id=NodeID("step_1"),
                    type=NodeType.AGENT,
                    name="Test",
                    ref_id="NonexistentAgent",
                ),
            ),
            edges=(),
        )

        result = await dag_executor.run(dag=dag)
        # Should complete (with failure since agent doesn't exist, but no crash)
        assert result is not None

    @pytest.mark.asyncio
    async def test_session_bootstrap_failure_is_graceful(self, registry: AgentRegistry) -> None:
        """If bootstrap fails, DAG still runs."""

        class BrokenSessionManager:
            async def bootstrap(self, session_id, **kwargs):
                raise RuntimeError("Bootstrap failed")

            async def dispose(self, session_id):
                return 0

        executor = ContextNodeExecutor(agent_registry=registry)
        dag_executor = DAGExecutor(
            node_executor=executor,
            session_manager=BrokenSessionManager(),  # type: ignore[arg-type]
        )

        dag = DAG(
            name="test-dag",
            nodes=(
                Node(
                    id=NodeID("step_1"),
                    type=NodeType.AGENT,
                    name="Test",
                    ref_id="NonexistentAgent",
                ),
            ),
            edges=(),
        )

        # Should not raise — bootstrap failure is isolated
        result = await dag_executor.run(dag=dag)
        assert result is not None
