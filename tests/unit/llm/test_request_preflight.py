"""Provider-specific preflight must count actual payloads and fail closed."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from cemaf.core.types import TokenCount
from cemaf.llm.gemini import GeminiClient
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.openai_responses import OpenAIResponsesLLMClient
from cemaf.llm.preflight import ProviderPreflightError
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message, ToolDefinition
from cemaf.llm.resilient import ResilientLLMClient
from cemaf.resilience.retry import RetryConfig, RetryPolicy


async def test_openai_counter_counts_rendered_tools_and_overridden_model():
    count = AsyncMock(return_value=SimpleNamespace(input_tokens=321))
    client = OpenAIResponsesLLMClient(
        client=SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=count)))
    )
    config = client.config.model_copy(update={"model": "pinned-model"})
    measured = await client.count_request(
        messages=[Message.system("Trusted instructions"), Message.user("Question")],
        tools=[
            ToolDefinition(
                name="lookup",
                description="Search",
                required=("query",),
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ],
        config=config,
    )
    request = count.call_args.kwargs
    assert measured.exact and measured.input_tokens == 321
    assert request["model"] == "pinned-model" and request["instructions"] == "Trusted instructions"
    assert request["tools"][0]["parameters"]["required"] == ["query"]
    assert request["input"][0]["content"] == "Question"


@pytest.mark.parametrize("count", [None, -1, True, "123"])
async def test_openai_strict_counter_rejects_invalid_counts(count):
    endpoint = AsyncMock(return_value=SimpleNamespace(input_tokens=count))
    client = OpenAIResponsesLLMClient(
        client=SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=endpoint)))
    )
    with pytest.raises(ValueError, match="invalid input token count"):
        await client.count_request(messages=[Message.user("Question")], tools=[], config=client.config)


async def test_openai_preflight_never_silently_falls_back_or_discloses_error_credentials():
    endpoint = AsyncMock(side_effect=RuntimeError("Credential SECRET in provider response"))
    client = OpenAIResponsesLLMClient(
        client=SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=endpoint)))
    )
    with pytest.raises(ProviderPreflightError) as error:
        await client.count_request(messages=[Message.user("Question")], tools=[], config=client.config)
    assert "SECRET" not in str(error.value)


async def test_gemini_counts_system_instruction_tools_and_schema_without_key_in_url(monkeypatch):
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"totalTokens": 444})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "cemaf.llm.gemini.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    client = GeminiClient(api_key="SECRET", use_vertex=False)
    config = LLMConfig(
        model="pinned-gemini",
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    result = await client.count_request(
        messages=[Message.system("Trusted instructions"), Message.user("Untrusted evidence")],
        tools=[ToolDefinition(name="lookup", description="Search")],
        config=config,
    )
    import json

    payload = json.loads(captured[0].content)["generateContentRequest"]
    assert result.exact and result.input_tokens == 444
    assert "SECRET" not in str(captured[0].url)
    assert captured[0].headers["x-goog-api-key"] == "SECRET"
    assert payload["model"] == "models/pinned-gemini"
    assert payload["systemInstruction"]["parts"][0]["text"] == "Trusted instructions"
    assert payload["contents"][0]["parts"][0]["text"] == "Untrusted evidence"
    assert payload["generationConfig"]["responseSchema"] == config.response_schema
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "lookup"


@pytest.mark.parametrize(
    "error,expected_attempts",
    [("Unavailable (503)", 3), ("Invalid authentication (401)", 1), ("Connection rejected (401)", 1)],
)
async def test_resilience_charges_billed_failed_results_without_retrying_permanent_errors(
    error, expected_attempts
):
    class BilledFailure(MockLLMClient):
        attempts = 0

        async def complete(self, *args, **kwargs):
            self.attempts += 1
            return CompletionResult(
                success=False, error=error, prompt_tokens=TokenCount(7), completion_tokens=TokenCount(2)
            )

    raw = BilledFailure()
    wrapped = ResilientLLMClient(
        client=raw, retry=RetryPolicy(RetryConfig(max_attempts=3, initial_delay_seconds=0))
    )
    result = await wrapped.complete([Message.user("Question")])
    assert not result.success and raw.attempts == expected_attempts
    assert result.prompt_tokens == 7 * expected_attempts
    assert result.completion_tokens == 2 * expected_attempts
    assert result.total_tokens == 9 * expected_attempts


async def test_run_logging_snapshots_mutable_request_fields_before_adapter_execution():
    from cemaf.llm.instrumented import InstrumentedLLMClient
    from cemaf.observability.run_logger import InMemoryRunLogger, RunRecord

    class MutatingAdapter(MockLLMClient):
        async def complete(self, messages, tools=None, config_override=None, **kwargs):
            messages[0].metadata["tag"] = "changed"
            messages[0].content[0]["text"] = "changed"
            tools[0].parameters["changed"] = True
            return await super().complete(messages, tools, config_override, **kwargs)

    logger = InMemoryRunLogger()
    logger.start_run(run_id="snapshot")
    client = InstrumentedLLMClient(client=MutatingAdapter(), run_logger=logger)
    messages = [Message.user([{"type": "text", "text": "Original question"}], metadata={"tag": "original"})]
    tools = [ToolDefinition(name="lookup", description="Search", parameters={"type": "object"})]
    await client.complete(messages, tools=tools)
    call = RunRecord.from_dict(logger.end_run().to_dict()).llm_calls[0]
    assert call.input_messages[0]["content"][0]["text"] == "Original question"
    assert call.input_messages[0]["metadata"]["tag"] == "original"
    assert "changed" not in call.input_tools[0]["parameters"]


async def test_gemini_candidate_failure_preserves_reported_usage(monkeypatch):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "candidates": [],
                "usageMetadata": {"promptTokenCount": 20, "thoughtsTokenCount": 5, "totalTokenCount": 25},
            },
        )
    )
    monkeypatch.setattr(
        "cemaf.llm.gemini.httpx.AsyncClient", lambda **kwargs: original_client(transport=transport, **kwargs)
    )
    result = await GeminiClient(api_key="test-key", use_vertex=False).complete([Message.user("Question")])
    assert not result.success
    assert result.prompt_tokens == 20 and result.completion_tokens == 5
    assert result.total_tokens == 25


async def test_gemini_legacy_and_request_counters_share_native_system_framing(monkeypatch):
    import json

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"totalTokens": 42})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "cemaf.llm.gemini.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    client = GeminiClient(api_key="test-key", use_vertex=False)
    messages = [Message.system("Trusted policy"), Message.user("Untrusted evidence")]
    assert await client.count_tokens_exact(messages) == 42
    assert (await client.count_request(messages=messages, tools=[], config=client.config)).input_tokens == 42
    assert requests[0] == requests[1]
    assert requests[0]["generateContentRequest"]["systemInstruction"]["parts"] == [{"text": "Trusted policy"}]
    assert requests[0]["generateContentRequest"]["contents"][0]["parts"] == [{"text": "Untrusted evidence"}]
