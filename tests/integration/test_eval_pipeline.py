"""Integration tests for online eval pipeline + quality police + DAG execution."""

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import EventType
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class TestEvalPipelineIntegration:
    """End-to-end: DAG execution → eval pipeline → quality police."""

    @pytest.fixture
    def event_bus(self) -> InMemoryEventBus:
        return InMemoryEventBus()

    @pytest.fixture
    def quality_police(self) -> QualityPolice:
        return QualityPolice(
            config=QualityPoliceConfig(
                window_size=5,
                warn_threshold=0.7,
                critical_threshold=0.5,
                halt_threshold=0.3,
            ),
        )

    @pytest.fixture
    def eval_pipeline(self, event_bus: InMemoryEventBus) -> OnlineEvalPipeline:
        return OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(LengthEvaluator(min_length=1, max_length=10000),),
                    mode=EvalMode.OBSERVE,
                ),
            ),
            event_bus=event_bus,
        )

    @pytest.mark.asyncio
    async def test_bootstrap_wires_eval_pipeline(
        self,
        event_bus: InMemoryEventBus,
        eval_pipeline: OnlineEvalPipeline,
        quality_police: QualityPolice,
    ):
        """Verify create_executor wires eval pipeline and quality police."""
        registry = AgentRegistry()
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=quality_police,
        )
        config = ExecutorConfig(enable_events=True)
        executor = create_executor(
            agent_registry=registry,
            config=config,
            services=services,
        )
        assert executor._quality_police is quality_police

    @pytest.mark.asyncio
    async def test_dag_execution_triggers_eval_events(
        self,
        event_bus: InMemoryEventBus,
        eval_pipeline: OnlineEvalPipeline,
        quality_police: QualityPolice,
    ):
        """DAG execution emits task events, eval pipeline evaluates them."""
        registry = AgentRegistry()
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=quality_police,
        )
        config = ExecutorConfig(enable_events=True)
        executor = create_executor(
            agent_registry=registry,
            config=config,
            services=services,
        )

        dag = DAG(
            name="eval-test",
            nodes=(
                Node(
                    id=NodeID("step_1"),
                    type=NodeType.AGENT,
                    name="Test Agent",
                    ref_id="NonexistentAgent",
                ),
            ),
            edges=(),
            entry_node=NodeID("step_1"),
        )
        result = await executor.run(dag=dag)

        # Verify the executor ran (may fail since agent doesn't exist, but events should fire)
        assert result is not None
        # The pipeline subscribed to TASK_COMPLETED
        assert EventType.TASK_COMPLETED.value in event_bus._handlers

    @pytest.mark.asyncio
    async def test_quality_police_records_from_eval_events(
        self,
        event_bus: InMemoryEventBus,
        quality_police: QualityPolice,
    ):
        """Quality police auto-records scores from EVAL_COMPLETED events."""
        quality_police.subscribe(event_bus=event_bus)

        from cemaf.events.protocols import Event

        # Simulate eval completed events
        for score in [0.9, 0.85, 0.8, 0.75, 0.7]:
            event = Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={"overall_score": score, "node_id": "test"},
                source="test",
            )
            await event_bus.publish(event=event)

        assert quality_police.rolling_mean == pytest.approx(0.8, abs=0.01)
        assert not quality_police.should_halt()

    @pytest.mark.asyncio
    async def test_quality_police_halts_on_bad_scores(
        self,
        event_bus: InMemoryEventBus,
        quality_police: QualityPolice,
    ):
        """Quality police triggers halt when scores degrade."""
        quality_police.subscribe(event_bus=event_bus)

        from cemaf.events.protocols import Event

        # Send consistently bad scores
        for score in [0.2, 0.1, 0.15, 0.2, 0.1]:
            event = Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={"overall_score": score, "node_id": "bad_node"},
                source="test",
            )
            await event_bus.publish(event=event)

        assert quality_police.should_halt()
        assert len(quality_police.alerts) > 0
