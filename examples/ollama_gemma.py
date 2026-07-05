"""CEMAF + Ollama (Gemma 3) smoke test — runs a local LLM via OpenAI-compatible adapter.

Prereqs:
    brew install ollama && brew services start ollama
    ollama pull gemma3:4b   # or gemma3:12b (better quality, ~8GB)

Usage:
    uv run python examples/ollama_gemma.py
    CEMAF_OLLAMA_MODEL=gemma3:12b uv run python examples/ollama_gemma.py
"""

from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel, Field

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


class AskGoal(BaseModel):
    prompt: str = Field(description="User prompt for the local LLM")


class AskResult(BaseModel):
    answer: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LocalLLMAgent(Agent[AskGoal, AskResult]):
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @property
    def id(self) -> AgentID:
        return AgentID("LocalLLM")

    @property
    def description(self) -> str:
        return "Calls a local Ollama-hosted model via OpenAI-compatible API."

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(
        self,
        goal: AskGoal,
        context: AgentContext,
    ) -> AgentResult[AskResult]:
        completion = await self._llm.complete(
            messages=[
                Message.system(content="You are concise. One sentence answers."),
                Message.user(content=goal.prompt),
            ],
        )
        if not completion.success or completion.message is None:
            return AgentResult.fail(
                error=completion.error or "empty completion",
                state=AgentState(),
            )
        text = completion.message.content
        if isinstance(text, list):
            text = " ".join(block.get("text", "") for block in text if isinstance(block, dict))
        return AgentResult.ok(
            output=AskResult(
                answer=str(text).strip(),
                model=completion.model,
                prompt_tokens=int(completion.prompt_tokens),
                completion_tokens=int(completion.completion_tokens),
            ),
            state=AgentState(),
        )


async def _run(llm: LLMClient, *, model: str) -> None:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=LocalLLMAgent(llm=llm), goal_type=AskGoal)

    dag = DAG(name="ollama_gemma", description="Ask Gemma 3 locally via Ollama").add_node(
        node=Node.agent(
            id="ask",
            name="LocalLLM",
            agent_id="LocalLLM",
            input_mapping={
                "prompt": "In one sentence: what is context engineering?",
            },
            output_key="answer",
        ),
    )

    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(llm_client=llm),
    )
    run_result = await executor.run(dag=dag)

    print(f"Status: {run_result.status.value}")
    print(f"Model:  {model}")
    payload = run_result.final_context.data.get("answer")
    if payload is None:
        print("No answer in final_context.")
        return
    if isinstance(payload, AskResult):
        answer = payload
    elif isinstance(payload, dict):
        answer = AskResult.model_validate(payload)
    else:
        print(f"Answer: {payload}")
        return
    print(f"Answer: {answer.answer}")
    print(f"Tokens: prompt={answer.prompt_tokens} completion={answer.completion_tokens}")


async def smoke_main() -> None:
    from cemaf.llm.mock import MockLLMClient
    from cemaf.llm.protocols import LLMConfig

    llm = MockLLMClient(
        responses=["Context engineering is the deliberate shaping of inputs, memory, tools, and flow."],
        config=LLMConfig(model="mock-ollama"),
    )
    await _run(llm=llm, model="mock-ollama")


async def main() -> None:
    model = os.environ.get("CEMAF_OLLAMA_MODEL", "gemma3:4b")
    base_url = os.environ.get("CEMAF_OLLAMA_BASE_URL", "http://localhost:11434/v1")
    llm = create_llm_client(provider="ollama", model=model, base_url=base_url)
    await _run(llm=llm, model=model)


if __name__ == "__main__":
    asyncio.run(main())
