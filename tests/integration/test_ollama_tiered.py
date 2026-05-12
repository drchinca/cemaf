"""Integration test: tiered Ollama router wires through RuntimeServices → DAG.

Uses Mock LLM stand-ins for the two tiers so the test runs without an actual
Ollama daemon, but exercises the real `ModelRouter` + real `DAGExecutor` wiring
end-to-end. This proves the seam CEMAF.md requires for any new LLM integration.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf import (
    DAG,
    Agent,
    AgentContext,
    AgentRegistry,
    AgentResult,
    AgentState,
    Node,
    create_executor,
)
from cemaf.core.types import AgentID
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.model_router import ModelRoute, ModelRouter
from cemaf.llm.ollama import CharBasedEstimator
from cemaf.llm.protocols import LLMClient, Message
from cemaf.orchestration.services import RuntimeServices


class PromptGoal(BaseModel):
    prompt: str


class PromptResult(BaseModel):
    answer: str
    model: str


class EchoLLMAgent(Agent[PromptGoal, PromptResult]):
    """Agent that calls the RuntimeServices.llm_client and returns the model used."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @property
    def id(self) -> AgentID:
        return AgentID("EchoLLM")

    @property
    def description(self) -> str:
        return "Calls the injected LLM and reports which model answered."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: PromptGoal,
        context: AgentContext,
    ) -> AgentResult[PromptResult]:
        result = await self._llm.complete(messages=[Message.user(content=goal.prompt)])
        if not result.success or result.message is None:
            return AgentResult.fail(error=result.error or "no content", state=AgentState())
        text = result.message.content
        return AgentResult.ok(
            output=PromptResult(
                answer=str(text),
                model=result.model,
            ),
            state=AgentState(),
        )


def _build_router(escalation_chars: int = 50) -> ModelRouter:
    """Tiered router with two Mock clients labeled as gemma3:4b / gemma3:12b."""
    small = MockLLMClient(responses=["small-answer"])
    small._config = small._config.model_copy(update={"model": "gemma3:4b"})  # type: ignore[attr-defined]
    large = MockLLMClient(responses=["large-answer"])
    large._config = large._config.model_copy(update={"model": "gemma3:12b"})  # type: ignore[attr-defined]
    return ModelRouter(
        routes=[
            ModelRoute(threshold=0.5, client=small, model_name="gemma3:4b"),
            ModelRoute(threshold=1.0, client=large, model_name="gemma3:12b"),
        ],
        estimator=CharBasedEstimator(escalation_chars=escalation_chars),
    )


class TestTieredRouterInRuntimeServices:
    @pytest.mark.asyncio
    async def test_short_prompt_uses_small_tier_via_dag(self) -> None:
        """create_executor + RuntimeServices(llm_client=router) → agent hits small model."""
        router = _build_router(escalation_chars=50)
        agent = EchoLLMAgent(llm=router)

        registry = AgentRegistry()
        registry.register_agent(agent_instance=agent, goal_type=PromptGoal)

        dag = DAG(name="tiered_short", description="short prompt → small tier").add_node(
            node=Node.agent(
                id="ask",
                name="EchoLLM",
                agent_id="EchoLLM",
                input_mapping={"prompt": "hi"},
                output_key="result",
            ),
        )

        executor = create_executor(
            agent_registry=registry,
            services=RuntimeServices(llm_client=router),
        )
        run_result = await executor.run(dag=dag)

        assert run_result.success, f"dag failed: {run_result}"
        payload = run_result.final_context.data["result"]
        if isinstance(payload, PromptResult):
            parsed = payload
        elif isinstance(payload, dict):
            parsed = PromptResult.model_validate(payload)
        else:
            parsed = PromptResult.model_validate_json(payload)
        assert parsed.model == "gemma3:4b"
        assert "small" in parsed.answer

    @pytest.mark.asyncio
    async def test_long_prompt_escalates_to_large_tier_via_dag(self) -> None:
        router = _build_router(escalation_chars=50)
        agent = EchoLLMAgent(llm=router)

        registry = AgentRegistry()
        registry.register_agent(agent_instance=agent, goal_type=PromptGoal)

        long_prompt = "x" * 500
        dag = DAG(name="tiered_long", description="long prompt → large tier").add_node(
            node=Node.agent(
                id="ask",
                name="EchoLLM",
                agent_id="EchoLLM",
                input_mapping={"prompt": long_prompt},
                output_key="result",
            ),
        )

        executor = create_executor(
            agent_registry=registry,
            services=RuntimeServices(llm_client=router),
        )
        run_result = await executor.run(dag=dag)

        assert run_result.success, f"dag failed: {run_result}"
        payload = run_result.final_context.data["result"]
        if isinstance(payload, PromptResult):
            parsed = payload
        elif isinstance(payload, dict):
            parsed = PromptResult.model_validate(payload)
        else:
            parsed = PromptResult.model_validate_json(payload)
        assert parsed.model == "gemma3:12b"
        assert "large" in parsed.answer

    @pytest.mark.asyncio
    async def test_router_satisfies_llm_client_protocol(self) -> None:
        """ModelRouter must structurally satisfy LLMClient — no adapter needed."""
        router = _build_router()
        assert isinstance(router, LLMClient)
