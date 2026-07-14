"""Native validation pipelines block DAG outputs through the interceptor spine."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.interceptors import GateValidationInterceptor, create_interceptor_pipeline
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.validation.factories import create_validation_pipeline
from cemaf.validation.rules import RequiredFieldsRule


class _Goal(BaseModel):
    pass


class _InvalidAgent:
    @property
    def id(self) -> AgentID:
        return AgentID("InvalidAgent")

    @property
    def description(self) -> str:
        return "Returns structured output missing a required production field"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[dict[str, str]]:
        return AgentResult.ok(output={"summary": "incomplete"}, state=AgentState())


@pytest.mark.asyncio
async def test_native_required_fields_validation_rejects_and_blocks_downstream() -> None:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_InvalidAgent(), goal_type=_Goal)
    validator = create_validation_pipeline(rules=[RequiredFieldsRule(fields=("summary", "citations"))])
    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateValidationInterceptor(
                validator=validator,
                node_pattern="produce",
                interceptor_id="required_output_gate",
            ),
        )
    )
    produce = Node.agent(
        id="produce",
        name="produce",
        agent_id="InvalidAgent",
        output_key="draft",
    )
    downstream = Node.agent(
        id="publish",
        name="publish",
        agent_id="InvalidAgent",
        output_key="published",
    )
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(interceptor_pipeline=pipeline),
    )

    run = await executor.run(
        dag=DAG(
            name="validation-gate",
            nodes=(produce, downstream),
            edges=(Edge(source=produce.id, target=downstream.id),),
            entry_node=NodeID("produce"),
        )
    )

    assert run.status is RunStatus.FAILED
    assert len(run.node_results) == 1
    result = run.node_results[0]
    assert result.success is False
    assert "REQUIRED_FIELD_MISSING" in str(result.metadata)
    assert result.metadata["interceptors"]["gate_rejected"] is True
    assert run.final_context is not None
    assert run.final_context.get("draft") is None
    assert run.final_context.get("published") is None
