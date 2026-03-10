"""Tests for bootstrap composition root."""

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class TestCreateExecutor:
    """Test the composition root factory."""

    def test_minimal_creation(self):
        """Create executor with just a registry."""
        registry = AgentRegistry()
        executor = create_executor(agent_registry=registry)
        assert isinstance(executor, DAGExecutor)

    def test_with_config(self):
        """Create executor with custom config."""
        registry = AgentRegistry()
        config = ExecutorConfig(max_parallel=5, node_timeout_seconds=60.0)
        executor = create_executor(agent_registry=registry, config=config)
        assert isinstance(executor, DAGExecutor)
        assert executor._max_parallel == 5
        assert executor._node_timeout == 60.0

    def test_with_services(self):
        """Create executor with runtime services."""
        from cemaf.memory.factories import create_memory_manager, create_session_manager
        from cemaf.observability.run_logger import InMemoryRunLogger

        registry = AgentRegistry()
        memory_manager = create_memory_manager()
        session_manager = create_session_manager(memory_manager=memory_manager)
        run_logger = InMemoryRunLogger()

        services = RuntimeServices(
            run_logger=run_logger,
            memory_manager=memory_manager,
            session_manager=session_manager,
        )
        executor = create_executor(agent_registry=registry, services=services)
        assert isinstance(executor, DAGExecutor)
        assert executor._run_logger is run_logger
        assert executor._session_manager is session_manager

    def test_config_disables_services(self):
        """Config flags disable wiring of services."""
        from cemaf.observability.run_logger import InMemoryRunLogger

        registry = AgentRegistry()
        config = ExecutorConfig(enable_logging=False, enable_events=False)
        services = RuntimeServices(run_logger=InMemoryRunLogger())

        executor = create_executor(
            agent_registry=registry,
            config=config,
            services=services,
        )
        assert executor._run_logger is None
        assert executor._event_bus is None

    @pytest.mark.asyncio
    async def test_executor_runs_dag(self):
        """End-to-end: created executor can run a DAG."""
        from cemaf.core.enums import NodeType
        from cemaf.core.types import NodeID
        from cemaf.orchestration.dag import DAG, Node

        registry = AgentRegistry()
        executor = create_executor(agent_registry=registry)

        dag = DAG(
            name="test",
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
        result = await executor.run(dag=dag)
        assert result is not None
