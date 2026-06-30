"""
Deep Integration Test: Cognitive Model-Fidelity Escalation.

Validates the deepest "flesh" of CEMAF's cognitive self-healing and model routing:
1. Cost-conscious agent starts by querying a cheap, low-fidelity model tier.
2. The low-fidelity model fails a postflight compliance gate (PII leak).
3. The Postflight Interceptor triggers a POSTflight RECOVER with a hint.
4. On retry, the agent reads the recovery hint and escalates its cognitive capacity
   by calling the ModelRouter with Fidelity.HIGH.
5. The ModelRouter automatically bypasses the low-fidelity route and targets
   the high-fidelity route (large model).
6. The high-fidelity model produces safe, compliant output, passing the gate cleanly.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Fidelity
from cemaf.bootstrap import create_executor
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID
from cemaf.interceptors import (
    DecisionKind,
    PostflightDecision,
    PostInterceptor,
    RecoveryHint,
    create_interceptor_pipeline,
)
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.model_router import ModelRoute, ModelRouter
from cemaf.llm.protocols import Message
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices

# ============================================================================
# Simulated Components
# ============================================================================


class SafeGoal(BaseModel):
    objective: str = "Generate safe content"


class FidelityEscalatingAgent(Agent[SafeGoal, str]):
    """An agent that escalates model fidelity upon seeing recovery hints."""

    def __init__(self, llm_client: ModelRouter) -> None:
        self._llm = llm_client
        self.runs = 0

    @property
    def id(self) -> AgentID:
        return AgentID("EscalatingAgent")

    @property
    def description(self) -> str:
        return "Agent that dynamically escalates model tier under safety gates"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: SafeGoal, context: AgentContext) -> AgentResult[str]:
        self.runs += 1
        state = AgentState()

        # Read recovery hints
        hints = context.global_memory.get("__cemaf_recovery_hints__", [])

        # 1. Choose fidelity dynamically: escalate if we have failed previously
        if any(h.get("code") == "pii_leak" for h in hints):
            fidelity = Fidelity.HIGH  # Escalates to high-fidelity (large model)
        else:
            fidelity = Fidelity.LOW  # Cost-saving baseline (small model)

        # 2. Invoke the model router with selected fidelity
        result = await self._llm.complete(messages=[Message.user(goal.objective)], fidelity=fidelity)

        if not result.success:
            return AgentResult.fail(f"LLM failed: {result.error}", state)

        return AgentResult.ok(output=str(result.content), state=state)


class PIIBlockerInterceptor(PostInterceptor):
    """Postflight interceptor that blocks SSN leaks."""

    @property
    def interceptor_id(self) -> str:
        return "pii_blocker"

    async def post(self, *, node: Node, context: AgentContext, result: NodeResult) -> PostflightDecision:
        output_str = str(result.output)

        if "ssn 123-45" in output_str.lower():
            hint = RecoveryHint(
                interceptor_id=self.interceptor_id,
                code="pii_leak",
                detail="PII Violation: Raw SSN detected in low-fidelity generation stream.",
                suggested_action="Use high-fidelity redaction standard to mask any SSN.",
            )
            return PostflightDecision(
                kind=DecisionKind.RECOVER,
                interceptor_id=self.interceptor_id,
                reason="PII leak detected in model output",
                recovery_hint=hint,
            )

        return PostflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self.interceptor_id)


# ============================================================================
# Integration Test Case
# ============================================================================


@pytest.mark.asyncio
async def test_cognitive_fidelity_escalation_under_safety_gate() -> None:
    """Validate dynamic model escalation when compliance check fails."""
    # 1. Setup ModelRouter with tiered Mock routes
    # 'small' route: threshold 0.5, returns PII-leak output
    # 'large' route: threshold 1.0, returns redacted output
    small_client = MockLLMClient(responses=["Report output: SSN 123-45-678 has been matched."])
    large_client = MockLLMClient(responses=["Report output: SSN [REDACTED] has been matched."])

    router = ModelRouter(
        routes=[
            ModelRoute(threshold=0.5, model_name="small", client=small_client),
            ModelRoute(threshold=1.0, model_name="large", client=large_client),
        ]
    )

    # 2. Setup Agent Registry & Interceptor pipeline
    agent_instance = FidelityEscalatingAgent(llm_client=router)
    registry = AgentRegistry()
    registry.register_agent(agent_instance=agent_instance, goal_type=SafeGoal)

    pipeline = create_interceptor_pipeline(interceptors=(PIIBlockerInterceptor(),))

    # 3. Setup RuntimeServices and Executor
    services = RuntimeServices(interceptor_pipeline=pipeline, llm_client=router)

    executor = create_executor(
        agent_registry=registry, services=services, config=ExecutorConfig(enable_events=False)
    )

    # 4. Construct DAG
    dag = DAG(name="fidelity_escalation_dag")
    writer_node = Node.agent(
        id="writer_node", name="writer", agent_id="EscalatingAgent", output_key="secure_report"
    )
    dag = dag.add_node(writer_node)

    # 5. Run Execution
    result = await executor.run(dag)

    # 6. Verify Invariants
    assert result.success is True
    assert result.status is RunStatus.COMPLETED

    # Assert agent ran exactly twice
    assert agent_instance.runs == 2

    # Assert model escalation worked deterministically:
    # Run 1: 'small' model called once (returned PII leak)
    # Run 2: 'large' model called once (returned redacted text)
    assert len(small_client.calls) == 1
    assert len(large_client.calls) == 1

    # Assert final context contains the safe high-fidelity output
    final_output = result.final_context.get("secure_report")
    assert final_output is not None
    assert "REDACTED" in final_output
    assert "123-45" not in final_output
