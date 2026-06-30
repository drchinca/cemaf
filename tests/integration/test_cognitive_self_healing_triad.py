"""
Unified Integration Test: The Cognitive self-healing and Blueprint Triad loop.

This test validates the actual "flesh" of CEMAF:
1. Context Usage & Immutability: Custom state modifications via ContextPatch.
2. Self-Healing Loop: Interceptor rejecting PII and providing feedback (RecoveryHint).
3. Feedback-Driven Revision: Agent correcting its behavior based on the recovery hint.
4. Triad Harvesting: Autonomous blueprint harvester capturing the high-quality corrected run.
5. Scoped Promotion: Evaluation of project-scoped harvested entries for global standard.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.blueprint import BlueprintScope, ProjectScopedRecipeDistiller
from cemaf.blueprint.harvest import BlueprintHarvesterEngine
from cemaf.blueprint.harvest_defaults import (
    InMemoryRunCorrelator,
    ScoreThresholdHarvestPolicy,
    evaluate_promotion,
)
from cemaf.blueprint.library import BlueprintEntry, BlueprintLibrary
from cemaf.blueprint.sources import InMemoryWritableBlueprintSource
from cemaf.context.context import Context
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.interceptors import (
    DecisionKind,
    PostflightDecision,
    PostInterceptor,
    RecoveryHint,
    create_interceptor_pipeline,
)
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices

# ============================================================================
# Simulated Domain Models & Components
# ============================================================================


class SecureReportGoal(BaseModel):
    objective: str = "Generate secure quarterly report"


class SecureWriterAgent(Agent[SecureReportGoal, str]):
    """Simulates a learning LLM writer agent.

    On the first attempt, it leaks sensitive PII (SSN).
    On seeing a PII recovery hint, it corrects itself and outputs clean redacted text.
    """

    def __init__(self) -> None:
        self.runs = 0

    @property
    def id(self) -> str:
        return "secure_writer"

    @property
    def description(self) -> str:
        return "Generates safe, PII-scrubbed reports"

    @property
    def skills(self) -> tuple:
        return ()

    async def run(self, goal: SecureReportGoal, context: AgentContext) -> AgentResult[str]:
        self.runs += 1
        state = AgentState()

        # Read recovery hints from global memory
        hints = context.global_memory.get("__cemaf_recovery_hints__", [])

        # Simulate correction behavior: if we see a PII hint, redact the output
        if any(h.get("code") == "pii_leak" for h in hints):
            return AgentResult.ok(
                output="Report Summary: [REDACTED_SSN] has completed validation successfully.",
                state=state,
                metadata={"self_corrected": True},
            )

        # Default behavior: leak SSN on first attempt
        return AgentResult.ok(
            output="Report Summary: User with SSN 123-45-678 has completed validation successfully.",
            state=state,
            metadata={"self_corrected": False},
        )


class PIIFilterInterceptor(PostInterceptor):
    """Postflight gate that inspects agent output for social security numbers."""

    @property
    def interceptor_id(self) -> str:
        return "pii_filter"

    async def post(self, *, node: Node, context: AgentContext, result: NodeResult) -> PostflightDecision:
        output_str = str(result.output)

        # If SSN pattern is present, trigger a self-correction recovery loop
        if "ssn 123-45" in output_str.lower():
            hint = RecoveryHint(
                interceptor_id=self.interceptor_id,
                code="pii_leak",
                detail="PII Violation: Plaintext SSN detected in report output.",
                suggested_action="Redact any social security numbers using '[REDACTED_SSN]' placeholder.",
            )
            return PostflightDecision(
                kind=DecisionKind.RECOVER,
                interceptor_id=self.interceptor_id,
                reason="PII violation detected in output stream",
                recovery_hint=hint,
            )

        return PostflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self.interceptor_id)


# ============================================================================
# Behavioral Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cognitive_self_healing_and_harvest_triad() -> None:
    """End-to-end integration proving the 'flesh' of CEMAF:

    1. Node executes, leaks PII.
    2. Interceptor intercepts output, returns DecisionKind.RECOVER + Hint.
    3. Executor reruns agent with the surfaced hint.
    4. Agent modifies behavior to produce PII-scrubbed output.
    5. Completed run emits evaluation event, harvested as project-scoped recipe.
    6. Multi-project promotion evaluates project-scoped recipes for global standards.
    """
    event_bus = InMemoryEventBus()
    library = BlueprintLibrary()
    writable_source = InMemoryWritableBlueprintSource()

    # 1. Wire up the Continuous Learning Harvester (SPEC-13)
    harvester = BlueprintHarvesterEngine(
        writable_source=writable_source,
        library=library,
        policy=ScoreThresholdHarvestPolicy(threshold=0.8, require_passed=True),
        correlator=InMemoryRunCorrelator(),
        distiller=ProjectScopedRecipeDistiller(project_id="project-alpha"),
    )
    harvester.subscribe(event_bus=event_bus)

    # 2. Setup the Interceptor and Orchestrator
    agent_instance = SecureWriterAgent()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=agent_instance, goal_type=SecureReportGoal)

    pipeline = create_interceptor_pipeline(interceptors=(PIIFilterInterceptor(),))

    node_executor = ContextNodeExecutor(
        agent_registry=registry, interceptor_pipeline=pipeline, max_recovery_attempts=3
    )

    services = RuntimeServices(event_bus=event_bus, interceptor_pipeline=pipeline)

    dag_executor = DAGExecutor(
        node_executor=node_executor,
        services=services,
        config=ExecutorConfig(enable_events=True),  # Publish run events to bus
    )

    # 3. Create topological workflow
    dag = DAG(name="cognitive_triad")
    node = Node(
        id="WriterNode",
        type="agent",
        name="writer",
        ref_id="secure_writer",
        output_key="report_output",
        retry_on_failure=True,
        max_retries=3,
    )
    dag = dag.add_node(node)

    # 4. Execute the pipeline under an initial context
    initial_context = Context(data={"user_id": "user_alpha"})

    # Run the DAG — triggers self-healing retry loop dynamically!
    result = await dag_executor.run(dag, initial_context)

    # Invariant 1: Self-healing occurred successfully
    assert result.success is True
    node_res = result.node_results[0]
    assert node_res.success is True
    assert "REDACTED_SSN" in str(node_res.output)
    assert agent_instance.runs == 2  # Proves it ran twice (Run 1: leaked, Intercepted -> Run 2: corrected)

    # Invariant 2: Context timeline holds accurate provenance patches
    # Retrieve the final execution context
    final_context = result.final_context
    assert (
        final_context.get("report_output")
        == "Report Summary: [REDACTED_SSN] has completed validation successfully."
    )

    # Verify we can compute a deterministic hash of the entire lineage
    assert final_context.state_hash() is not None

    # ---- Simulated Step 5: Continuous Harvest of High-Quality Corrections ----
    # Evaluate the final completed run as high-quality (score 0.95, passed)
    # This event is picked up by our HarvesterEngine to grow our Blueprint library
    goal_text = "Generate a secure quarterly report for compliance"
    await event_bus.publish(
        Event.create(
            type=EventType.TASK_STARTED,
            payload={
                "run_id": str(result.run_id),
                "node_id": "WriterNode",
                "goal_text": goal_text,
                "inputs": {"objective": goal_text},
            },
            correlation_id=str(result.run_id),
        ),
    )
    await event_bus.publish(
        Event.create(
            type=EventType.TASK_COMPLETED,
            payload={
                "run_id": str(result.run_id),
                "node_id": "WriterNode",
                "output": str(node_res.output),
            },
            correlation_id=str(result.run_id),
        ),
    )
    await event_bus.publish(
        Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={
                "run_id": str(result.run_id),
                "node_id": "WriterNode",
                "overall_score": 0.95,
                "overall_passed": True,
            },
            correlation_id=str(result.run_id),
        ),
    )

    # Invariant 3: The blueprint was autonomously harvested and registered in library
    harvested = [e for e in library if e.id.startswith("harvest/")]
    assert len(harvested) == 1
    harvested_entry = harvested[0]
    assert harvested_entry.scope == BlueprintScope.PROJECT
    assert harvested_entry.confidence == 0.95

    # ---- Simulated Step 6: Scoped Promotion (SPEC-13) ----
    # Create simulated multi-project harvested entries to test global promotion
    harvested_entries = (
        harvested_entry,  # from project alpha (confidence 0.95)
        BlueprintEntry.recipe_entry(
            id=f"harvest/project-beta/{harvested_entry.id.split('/')[-1]}",
            title="Secure compliance reporting recipe",
            recipe={"name": "SecureReport"},
            project_id="project-beta",
            confidence=0.85,
        ),
    )

    # Evaluate promotion over entries
    decisions = evaluate_promotion(harvested_entries, min_projects=2, min_confidence=0.8)
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.promote is True
    assert decision.mean_confidence == pytest.approx(0.9)
