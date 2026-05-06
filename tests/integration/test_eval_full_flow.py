"""Integration test: eval pipeline → quality police event chain."""

import pytest

from cemaf.evals.evaluators import LengthEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from tests.unit.evals.conftest import drain_tasks


class TestFullEvalFlow:
    """End-to-end: TASK_COMPLETED → eval pipeline → EVAL_COMPLETED → quality police."""

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
                    evaluators=(LengthEvaluator(min_length=1, max_length=100),),
                    mode=EvalMode.OBSERVE,
                ),
            ),
            event_bus=event_bus,
        )

    @pytest.mark.asyncio
    async def test_event_chain_task_to_eval_to_police(
        self,
        event_bus: InMemoryEventBus,
        eval_pipeline: OnlineEvalPipeline,
        quality_police: QualityPolice,
    ) -> None:
        """Verify event chain: TASK_COMPLETED → eval pipeline → EVAL_COMPLETED → quality police."""
        eval_pipeline.subscribe()
        quality_police.subscribe(event_bus=event_bus)

        event = Event.create(
            type=EventType.TASK_COMPLETED,
            payload={
                "node_id": "test_node",
                "output": "This is a test output",
                "success": True,
            },
            source="test",
        )
        await event_bus.publish(event=event)
        await drain_tasks()

        # Pipeline should have evaluated
        assert len(eval_pipeline.results) == 1
        assert eval_pipeline.results[0]["node_id"] == "test_node"
        assert eval_pipeline.results[0]["overall_passed"] is True
        assert eval_pipeline.results[0]["overall_score"] > 0

        # Police should have recorded the score from the EVAL_COMPLETED event
        police_state = quality_police.to_dict()
        assert police_state["scores_count"] == 1
        assert quality_police.rolling_mean == pytest.approx(1.0)
        assert not quality_police.should_halt()

    @pytest.mark.asyncio
    async def test_multiple_tasks_accumulate_in_police(
        self,
        event_bus: InMemoryEventBus,
        eval_pipeline: OnlineEvalPipeline,
        quality_police: QualityPolice,
    ) -> None:
        """Multiple TASK_COMPLETED events accumulate scores in quality police."""
        eval_pipeline.subscribe()
        quality_police.subscribe(event_bus=event_bus)

        for i in range(3):
            event = Event.create(
                type=EventType.TASK_COMPLETED,
                payload={
                    "node_id": f"node_{i}",
                    "output": f"Output number {i}",
                    "success": True,
                },
                source="test",
            )
            await event_bus.publish(event=event)
        await drain_tasks()

        assert len(eval_pipeline.results) == 3
        # All three scores should be recorded in police
        assert quality_police.to_dict()["scores_count"] == 3

    @pytest.mark.asyncio
    async def test_failing_eval_does_not_record_in_police(
        self,
        event_bus: InMemoryEventBus,
        quality_police: QualityPolice,
    ) -> None:
        """When eval pipeline errors, no EVAL_COMPLETED fires, police stays pristine."""
        from tests.unit.evals.conftest import FailingEvaluator

        pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(FailingEvaluator(error_message="boom"),),
                    mode=EvalMode.OBSERVE,
                ),
            ),
            event_bus=event_bus,
        )
        pipeline.subscribe()
        quality_police.subscribe(event_bus=event_bus)

        event = Event.create(
            type=EventType.TASK_COMPLETED,
            payload={
                "node_id": "bad_node",
                "output": "some output",
                "success": True,
            },
            source="test",
        )
        await event_bus.publish(event=event)
        await drain_tasks()

        # Pipeline should have zero results (error path)
        assert len(pipeline.results) == 0
        # Police should still be at default (no scores recorded)
        assert quality_police.rolling_mean == 1.0

    @pytest.mark.asyncio
    async def test_bootstrap_wires_pipeline_and_police(
        self,
        event_bus: InMemoryEventBus,
        eval_pipeline: OnlineEvalPipeline,
        quality_police: QualityPolice,
    ) -> None:
        """create_executor wires both eval pipeline and police subscriptions."""
        from cemaf.agents.registry import AgentRegistry
        from cemaf.bootstrap import create_executor
        from cemaf.orchestration.executor import ExecutorConfig
        from cemaf.orchestration.services import RuntimeServices

        registry = AgentRegistry()
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=quality_police,
        )
        config = ExecutorConfig(enable_events=True)
        create_executor(
            agent_registry=registry,
            config=config,
            services=services,
        )

        # After bootstrap, simulate a TASK_COMPLETED and verify the chain fires
        event = Event.create(
            type=EventType.TASK_COMPLETED,
            payload={
                "node_id": "bootstrapped_node",
                "output": "Bootstrapped output",
                "success": True,
            },
            source="test",
        )
        await event_bus.publish(event=event)
        await drain_tasks()

        assert len(eval_pipeline.results) == 1
        assert eval_pipeline.results[0]["node_id"] == "bootstrapped_node"
        assert quality_police.to_dict()["scores_count"] == 1
