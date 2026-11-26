"""Exercise caching through the installed SDK, resilient factory, and run logger.

The SDK serializes requests and parses completions/SSE itself; only the HTTP
transport is replaced. No credentials or live provider calls are required.
"""

import json
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from cemaf.llm.factories import (
    create_instrumented_client,
    create_llm_client,
    create_resilient_llm_client,
)
from cemaf.llm.protocols import LLMConfig, Message, ToolDefinition
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.services import RuntimeServices


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("resilient", [False, True])
async def test_prompt_caching_through_real_sdk_and_run_logger(monkeypatch, streaming, resilient):
    requests = []
    usage = {
        "input_tokens": 50,
        "output_tokens": 5,
        "cache_read_input_tokens": 1200,
        "cache_creation_input_tokens": 450,
    }
    response_message = {
        "id": "msg_cached",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": [{"type": "text", "text": "Cached answer"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": usage,
    }

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if not body.get("stream"):
            return httpx.Response(200, json=response_message)
        events = [
            {
                "type": "message_start",
                "message": {
                    **response_message,
                    "content": [],
                    "stop_reason": None,
                    "usage": {**usage, "output_tokens": 0},
                },
            },
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Cached answer"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
            {"type": "message_stop"},
        ]
        payload = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    sdk = anthropic.AsyncAnthropic(api_key="test-key", http_client=http_client, max_retries=0)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: sdk)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    metrics = MagicMock()
    if resilient:
        client = create_resilient_llm_client(
            provider="anthropic",
            model="claude-test",
            enable_caching=True,
            cache_ttl="1h",
            cache_threshold_tokens=0,
            metrics=metrics,
        )
        cfg = None
    else:
        client = create_llm_client("anthropic", api_key="test-key", model="claude-test")
        cfg = LLMConfig(model="claude-test", cache_control={"type": "ephemeral", "ttl": "1h"})

    logger = InMemoryRunLogger()
    services = RuntimeServices(llm_client=client, run_logger=logger)
    logged = create_instrumented_client(client=services.llm_client, run_logger=services.run_logger)
    logger.start_run(run_id="cached-run")
    messages = [
        Message.system("Stable instructions"),
        Message.user(
            [
                {"type": "text", "text": "Reference and question"},
            ]
        ),
    ]
    tools = [ToolDefinition(name="lookup", description="Look up a reference")]
    try:
        if streaming:
            chunks = [chunk async for chunk in logged.stream(messages, tools=tools, config_override=cfg)]
            assert chunks[-1].is_final
            assert chunks[-1].accumulated_content == "Cached answer"
            result = chunks[-1]
        else:
            result = await logged.complete(messages, tools=tools, config_override=cfg)
            assert result.success, result.error
            assert result.content == "Cached answer"
        assert result.prompt_tokens == 1700
        assert result.completion_tokens == 5
        assert result.metadata["cache_read_input_tokens"] == 1200
        assert result.metadata["cache_creation_input_tokens"] == 450
        record = logger.end_run()
        assert len(record.llm_calls) == 1
        assert record.llm_calls[0].input_tokens == 1700
        assert record.llm_calls[0].output_tokens == 5
        assert len(requests) == 1
        assert requests[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert requests[0]["messages"][0]["content"] == messages[1].content
        if resilient:
            assert requests[0]["tools"][-1]["cache_control"]["ttl"] == "1h"
            assert requests[0]["system"][-1]["cache_control"]["ttl"] == "1h"
            metrics.counter.assert_any_call("cemaf.llm.tokens_saved", 1200)
            metrics.counter.assert_any_call("cemaf.llm.cache.created", 450)
        assert tools[0].cache_control is None
        assert messages[0].metadata == {}
    finally:
        await sdk.close()
