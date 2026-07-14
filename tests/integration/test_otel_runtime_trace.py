"""Real OpenTelemetry SDK proof for RuntimeServices DAG and node telemetry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.types import AgentID, RunID
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.interceptors import GateEvalInterceptor, GateFailureMode, create_interceptor_pipeline
from cemaf.interceptors.types import RECOVERY_HINTS_KEY
from cemaf.observability.otel_tracer import OTelTracer
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _Goal(BaseModel):
    pass


class _RecoveringAgent:
    @property
    def id(self) -> AgentID:
        return AgentID("TracedWriter")

    @property
    def description(self) -> str:
        return "Produces one rejected draft and one accepted recovery"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[str]:
        if context.global_memory.get(RECOVERY_HINTS_KEY):
            return AgentResult.ok(
                output="accepted traced recovery " * 10,
                state=AgentState(),
                metadata={"cost_estimate_usd": 0.02, "tokens_total": 200},
            )
        return AgentResult.ok(
            output="short",
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.01, "tokens_total": 100},
        )


@pytest.mark.asyncio
async def test_runtime_services_exports_parented_node_cost_token_and_recovery_span() -> None:
    otel_trace = pytest.importorskip("opentelemetry.sdk.trace")
    export_module = pytest.importorskip("opentelemetry.sdk.trace.export")
    memory_exporter_module = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    exporter = memory_exporter_module.InMemorySpanExporter()
    provider = otel_trace.TracerProvider()
    provider.add_span_processor(export_module.SimpleSpanProcessor(exporter))
    tracer = OTelTracer(provider.get_tracer("cemaf.production-proof"))

    registry = AgentRegistry()
    registry.register_agent(agent_instance=_RecoveringAgent(), goal_type=_Goal)
    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="write",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        )
    )
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(
            tracer=tracer,
            interceptor_pipeline=pipeline,
            max_recovery_attempts=2,
        ),
    )
    node = Node.agent(id="write", name="write", agent_id="TracedWriter", output_key="draft")

    run = await executor.run(
        dag=DAG(name="otel-production-proof", nodes=(node,), edges=(), entry_node=node.id),
        run_id=RunID("otel-proof-run"),
    )

    assert run.success
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"cemaf.dag.run", "cemaf.node.attempt"}
    root = spans["cemaf.dag.run"]
    attempt = spans["cemaf.node.attempt"]
    assert attempt.context.trace_id == root.context.trace_id
    assert attempt.parent is not None
    assert attempt.parent.span_id == root.context.span_id
    assert attempt.attributes["cemaf.run.id"] == "otel-proof-run"
    assert attempt.attributes["cemaf.node.id"] == "write"
    assert attempt.attributes["cemaf.node.success"] is True
    assert attempt.attributes["cemaf.cost.usd"] == pytest.approx(0.03)
    assert attempt.attributes["cemaf.tokens.total"] == 300
    assert attempt.attributes["cemaf.recovery.attempts"] == 1
