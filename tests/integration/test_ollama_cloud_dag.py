"""DAG-level integration test: ollama-cloud through RuntimeServices → DAGExecutor.

Skipped unless OLLAMA_CLOUD_API_KEY is set. Wires the real ollama-cloud LLM
client into a real DAG run and verifies an agent receives a real LLM response.
This proves the full seam — factory → RuntimeServices → executor → agent —
end-to-end, not just the HTTP round-trip.
"""

from __future__ import annotations

import os

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
from cemaf.llm.factories import create_llm_client
from cemaf.llm.protocols import LLMClient, Message
from cemaf.orchestration.services import RuntimeServices

pytestmark = pytest.mark.skipif(
    not os.getenv("OLLAMA_CLOUD_API_KEY"),
    reason="OLLAMA_CLOUD_API_KEY not set; skipping live ollama-cloud DAG test",
)

FREE_TIER_MODELS = [
    "gpt-oss:20b-cloud",
    "gpt-oss:120b-cloud",
    "qwen3-coder:480b-cloud",
    "minimax-m2.1:cloud",
]


class PromptGoal(BaseModel):
    prompt: str


class PromptResult(BaseModel):
    answer: str
    model: str


class EchoLLMAgent(Agent[PromptGoal, PromptResult]):
    """Calls injected LLM, returns answer + model name."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @property
    def id(self) -> AgentID:
        return AgentID("EchoLLM")

    @property
    def description(self) -> str:
        return "Calls the injected LLM and reports the model that answered."

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
            return AgentResult.fail(
                error=result.error or "no content",
                state=AgentState(),
            )
        return AgentResult.ok(
            output=PromptResult(
                answer=str(result.message.content),
                model=result.model,
            ),
            state=AgentState(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", FREE_TIER_MODELS)
async def test_ollama_cloud_drives_real_dag(model: str) -> None:
    llm = create_llm_client(provider="ollama-cloud", model=model)
    agent = EchoLLMAgent(llm=llm)

    registry = AgentRegistry()
    registry.register_agent(agent_instance=agent, goal_type=PromptGoal)

    dag = DAG(name="ollama_cloud_smoke", description="real cloud LLM via DAG").add_node(
        node=Node.agent(
            id="ask",
            name="EchoLLM",
            agent_id="EchoLLM",
            input_mapping={"prompt": "Reply with the single word: pong"},
            output_key="result",
        ),
    )

    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(llm_client=llm),
    )
    run_result = await executor.run(dag=dag)

    assert run_result.success, f"dag failed for {model}: {run_result}"
    payload = run_result.final_context.data["result"]
    if isinstance(payload, PromptResult):
        parsed = payload
    elif isinstance(payload, dict):
        parsed = PromptResult.model_validate(payload)
    else:
        parsed = PromptResult.model_validate_json(payload)

    assert parsed.answer.strip(), f"empty answer from {model}"
    assert parsed.model, f"no model name reported by {model}"
