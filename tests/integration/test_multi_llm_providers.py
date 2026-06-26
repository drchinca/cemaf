"""Integration test: all LLM providers wire into CEMAF's RuntimeServices and executor.

Proves the full path: create_llm_client → RuntimeServices → create_executor → DAG runs.
Uses MockLLMClient for actual execution since we can't hit real APIs in CI.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf import DAG, AgentRegistry, Node, create_executor
from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.core.types import AgentID
from cemaf.llm.factories import create_llm_client, llm_registry
from cemaf.llm.gemini import GeminiClient
from cemaf.llm.openai_compat import OpenAICompatClient
from cemaf.llm.protocols import LLMClient
from cemaf.llm.resilient import ResilientLLMClient, create_resilient_client
from cemaf.orchestration.services import RuntimeServices


class PingGoal(BaseModel):
    pass


class PingResult(BaseModel):
    provider: str = ""


class PingAgent(Agent[PingGoal, PingResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Pinger")

    @property
    def description(self) -> str:
        return "Pings back"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: PingGoal, context: AgentContext) -> AgentResult[PingResult]:
        return AgentResult.ok(output=PingResult(provider="mock"), state=AgentState())


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_all_8_backends_registered(self) -> None:
        expected = {"mock", "anthropic", "openai", "ollama", "groq", "together", "gemini", "bedrock"}
        registered = set(llm_registry._factories.keys())
        assert expected.issubset(registered)

    def test_mock_creates_client(self) -> None:
        client = create_llm_client("mock")
        assert isinstance(client, LLMClient)

    def test_ollama_creates_openai_compat(self) -> None:
        client = create_llm_client("ollama", model="qwen3.5")
        assert isinstance(client, OpenAICompatClient)
        assert client.config.model == "qwen3.5"

    def test_openai_creates_openai_compat(self) -> None:
        client = create_llm_client("openai", api_key="sk-test", model="gpt-4o")
        assert isinstance(client, OpenAICompatClient)

    def test_gemini_creates_gemini_client(self) -> None:
        client = create_llm_client("gemini", api_key="AIza-test")
        assert isinstance(client, GeminiClient)

    def test_groq_points_to_groq_api(self) -> None:
        client = create_llm_client("groq", api_key="gsk-test")
        assert isinstance(client, OpenAICompatClient)
        assert "groq.com" in client._base_url

    def test_together_points_to_together_api(self) -> None:
        client = create_llm_client("together", api_key="tok-test")
        assert isinstance(client, OpenAICompatClient)
        assert "together.xyz" in client._base_url

    def test_bedrock_creates_llm_client(self) -> None:
        client = create_llm_client("bedrock")
        assert isinstance(client, LLMClient)


# ---------------------------------------------------------------------------
# RuntimeServices wiring
# ---------------------------------------------------------------------------


class TestRuntimeServicesWiring:
    def test_llm_client_in_services(self) -> None:
        client = create_llm_client("mock")
        services = RuntimeServices(llm_client=client)
        assert services.llm_client is client

    def test_resilient_wraps_any_provider(self) -> None:
        base = create_llm_client("ollama", model="gemma-4-27b")
        resilient = create_resilient_client(client=base)
        assert isinstance(resilient, ResilientLLMClient)
        assert resilient.config.model == "gemma-4-27b"

    @pytest.mark.asyncio
    async def test_executor_runs_with_mock_llm(self) -> None:
        """Full path: mock LLM → RuntimeServices → create_executor → DAG runs."""
        client = create_llm_client("mock")
        services = RuntimeServices(llm_client=client)

        registry = AgentRegistry()
        registry.register_agent(agent_instance=PingAgent(), goal_type=PingGoal)

        dag = DAG(name="llm_test", description="test LLM wiring")
        dag = dag.add_node(
            node=Node.agent(
                id="ping",
                name="Ping",
                agent_id="Pinger",
                output_key="pong",
            )
        )

        executor = create_executor(agent_registry=registry, services=services)
        result = await executor.run(dag=dag)

        assert result.success
        assert "pong" in result.final_context.data


# ---------------------------------------------------------------------------
# Provider switching
# ---------------------------------------------------------------------------


class TestProviderSwitching:
    def test_switch_provider_same_interface(self) -> None:
        """All providers return LLMClient — switchable at runtime."""
        providers = [
            ("mock", {}),
            ("ollama", {"model": "qwen3.5"}),
            ("openai", {"api_key": "sk-test", "model": "gpt-4o"}),
            ("gemini", {"api_key": "AIza-test"}),
            ("groq", {"api_key": "gsk-test"}),
            ("together", {"api_key": "tok-test"}),
            ("bedrock", {}),
        ]

        clients: list[LLMClient] = []
        for provider, kwargs in providers:
            client = create_llm_client(provider, **kwargs)
            assert isinstance(client, LLMClient), f"{provider} does not satisfy LLMClient"
            assert client.config.model, f"{provider} has no model"
            clients.append(client)

        assert len(clients) == 7

    def test_all_support_token_counting(self) -> None:
        """Every provider can count tokens."""
        providers = [
            create_llm_client("mock"),
            create_llm_client("ollama", model="test"),
            create_llm_client("openai", api_key="k"),
            create_llm_client("gemini", api_key="k"),
            create_llm_client("bedrock"),
        ]

        for client in providers:
            count = client.count_tokens(text="hello world")
            assert count > 0
