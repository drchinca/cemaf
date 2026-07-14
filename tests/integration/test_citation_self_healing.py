"""
Deep Integration Test: Citation Self-Correction and Quality Gating.

Validates the deepest "flesh" of CEMAF's self-healing context and quality systems:
1. Agent generating a CitedFact with supporting source Citations.
2. Postflight Interceptor running the CitationFormatRule (require_url=True).
3. Detecting a format violation (MISSING_URL) on the first generation attempt.
4. Raising a PostflightDecision.RECOVER with a highly detailed RecoveryHint.
5. CitingWriterAgent polling recovery hints, correcting the URL, and outputting valid citations.
6. Verification that the second attempt satisfies the CitationFormatRule cleanly.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.citation.models import Citation, CitedFact
from cemaf.citation.rules import CitationFormatRule
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID
from cemaf.interceptors import (
    GateFailureMode,
    GateValidationInterceptor,
    create_interceptor_pipeline,
)
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices
from cemaf.validation.factories import create_validation_pipeline

# ============================================================================
# Simulated Components
# ============================================================================


class CitingGoal(BaseModel):
    objective: str = "Compile fact sheet"


class CitingWriterAgent(Agent[CitingGoal, CitedFact]):
    """An agent that generates a CitedFact.

    On the first run, it omits the URL on its supporting citation.
    On seeing a 'MISSING_URL' recovery hint, it self-corrects and fills in the URL.
    """

    def __init__(self) -> None:
        self.runs = 0

    @property
    def id(self) -> AgentID:
        return AgentID("CitingWriter")

    @property
    def description(self) -> str:
        return "Writer that cites sources with full metadata"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: CitingGoal, context: AgentContext) -> AgentResult[CitedFact]:
        self.runs += 1
        state = AgentState()

        # Read recovery hints from global memory
        hints = context.global_memory.get("__cemaf_recovery_hints__", [])

        if any(h.get("code") == "MISSING_URL" for h in hints):
            # Correction: Provide complete citation URL
            citation = Citation(
                id="cit_core_01",
                source_id="doc_123",
                source_type="doc",
                title="CEMAF Core Specs",
                url="https://example.com/cemaf",
                confidence=0.95,
            )
            fact = CitedFact(
                id="fact_01", fact="CEMAF uses an immutable context pipeline.", citations=(citation,)
            )
            return AgentResult.ok(output=fact, state=state)

        # Defect: Citation has empty/None URL on first run
        citation = Citation(
            id="cit_core_01",
            source_id="doc_123",
            source_type="doc",
            title="CEMAF Core Specs",
            url=None,  # MISSING URL!
            confidence=0.95,
        )
        fact = CitedFact(
            id="fact_01", fact="CEMAF uses an immutable context pipeline.", citations=(citation,)
        )
        return AgentResult.ok(output=fact, state=state)


# ============================================================================
# Integration Test Case
# ============================================================================


@pytest.mark.asyncio
async def test_citation_quality_gate_and_self_healing() -> None:
    """Validate full multi-round citation format correction loop."""
    # 1. Setup Agent Registry and Interceptor pipeline
    agent_instance = CitingWriterAgent()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=agent_instance, goal_type=CitingGoal)

    validator = create_validation_pipeline(rules=[CitationFormatRule(require_url=True, require_title=True)])
    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateValidationInterceptor(
                validator=validator,
                node_pattern="citing_node",
                fail_on_warnings=True,
                on_failure=GateFailureMode.RECOVER,
                interceptor_id="citation_format_gate",
            ),
        )
    )

    # 2. Setup RuntimeServices and Executor
    services = RuntimeServices(interceptor_pipeline=pipeline)

    executor = create_executor(
        agent_registry=registry, services=services, config=ExecutorConfig(enable_events=False)
    )

    # 3. Construct DAG
    dag = DAG(name="citation_quality_dag")
    writer_node = Node.agent(
        id="citing_node", name="writer", agent_id="CitingWriter", output_key="compiled_fact"
    )
    dag = dag.add_node(writer_node)

    # 4. Run Execution
    result = await executor.run(dag)

    # 5. Verify Invariants
    assert result.success is True
    assert result.status is RunStatus.COMPLETED

    # Assert self-correction retry completed successfully
    assert agent_instance.runs == 2  # Run 1: deficient, Intercepted -> Run 2: corrected

    # Assert final output contains complete corrected URL string
    node_res = result.node_results[0]
    assert node_res.success is True

    final_output = result.final_context.get("compiled_fact")
    assert final_output is not None
    assert "fact_01" in final_output
    assert "https://example.com/cemaf" in final_output  # Successfully corrected!
