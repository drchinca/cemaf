"""DAG-level integration test: ollama-cloud through RuntimeServices → DAGExecutor.

Wires the ollama-cloud LLM client into a real DAG run and verifies an agent
receives a parsed LLM response. The HTTP endpoint is faked so the default suite
does not require external credentials.
"""

from __future__ import annotations

from typing import Any

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
from cemaf.llm.factories import DEFAULT_OLLAMA_CLOUD_MODEL, create_llm_client
from cemaf.llm.protocols import LLMClient, Message
from cemaf.orchestration.services import RuntimeServices


class _FakeResponse:
    status_code = 200
    text = ""

    def json(self) -> dict[str, Any]:
        return {
            "model": DEFAULT_OLLAMA_CLOUD_MODEL,
            "choices": [
                {
                    "message": {"role": "assistant", "content": "pong"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }


class _FakeAsyncClient:
    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        assert url == "https://ollama.com/v1/chat/completions"
        assert json["model"] == DEFAULT_OLLAMA_CLOUD_MODEL
        assert headers["Authorization"] == "Bearer test-ollama-key"
        return _FakeResponse()


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
async def test_ollama_cloud_drives_real_dag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cemaf.llm.openai_compat.httpx.AsyncClient",
        lambda *, timeout: _FakeAsyncClient(),
    )
    llm = create_llm_client(
        provider="ollama-cloud",
        api_key="test-ollama-key",
        model=DEFAULT_OLLAMA_CLOUD_MODEL,
    )
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

    assert run_result.success, f"dag failed: {run_result}"
    payload = run_result.final_context.data["result"]
    if isinstance(payload, PromptResult):
        parsed = payload
    elif isinstance(payload, dict):
        parsed = PromptResult.model_validate(payload)
    else:
        parsed = PromptResult.model_validate_json(payload)

    assert parsed.answer.strip() == "pong"
    assert parsed.model == DEFAULT_OLLAMA_CLOUD_MODEL
