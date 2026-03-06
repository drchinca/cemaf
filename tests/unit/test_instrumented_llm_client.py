"""Contract tests for InstrumentedLLMClient."""

import pytest

from cemaf.llm.protocols import CompletionResult, LLMClient, Message
from cemaf.observability.run_logger import InMemoryRunLogger


class TestInstrumentedLLMClientContract:
    """Contract: InstrumentedLLMClient wraps any LLMClient and auto-records every call."""

    def test_satisfies_llm_client_protocol(self) -> None:
        """InstrumentedLLMClient must satisfy the LLMClient protocol."""
        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        inner = MockLLMClient()
        client = InstrumentedLLMClient(client=inner, run_logger=logger)

        assert isinstance(client, LLMClient)

    @pytest.mark.asyncio
    async def test_complete_records_llm_call(self) -> None:
        """Every complete() call must produce an LLMCall in the RunLogger."""
        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        logger.start_run(run_id="test-run", dag_name="test")

        inner = MockLLMClient()
        client = InstrumentedLLMClient(client=inner, run_logger=logger)

        messages = [Message.user("Hello")]
        result = await client.complete(messages=messages)

        assert result.success is True

        record = logger.get_current_record()
        assert record is not None
        assert len(record.llm_calls) == 1

        llm_call = record.llm_calls[0]
        assert llm_call.id.startswith("llm_")
        assert llm_call.output != ""
        assert llm_call.input_tokens >= 0
        assert llm_call.output_tokens >= 0

    @pytest.mark.asyncio
    async def test_complete_passes_through_to_inner_client(self) -> None:
        """The wrapped result must be identical to what the inner client returns."""
        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        inner = MockLLMClient()

        direct_result = await inner.complete(messages=[Message.user("test")])

        logger.start_run(run_id="test-run", dag_name="test")
        client = InstrumentedLLMClient(client=inner, run_logger=logger)
        wrapped_result = await client.complete(messages=[Message.user("test")])

        assert wrapped_result.success == direct_result.success
        assert wrapped_result.model == direct_result.model

    @pytest.mark.asyncio
    async def test_records_node_and_agent_ids(self) -> None:
        """LLMCall must carry node_id and agent_id when set on the wrapper."""
        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        logger.start_run(run_id="test-run", dag_name="test")

        inner = MockLLMClient()
        client = InstrumentedLLMClient(
            client=inner,
            run_logger=logger,
            node_id="node-researcher",
            agent_id="agent-researcher",
        )

        await client.complete(messages=[Message.user("Hello")])

        record = logger.get_current_record()
        assert record is not None
        llm_call = record.llm_calls[0]
        assert llm_call.node_id == "node-researcher"
        assert llm_call.agent_id == "agent-researcher"

    @pytest.mark.asyncio
    async def test_failed_complete_still_records(self) -> None:
        """Even failed LLM calls must be recorded for audit trail."""
        from unittest.mock import AsyncMock

        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        logger.start_run(run_id="test-run", dag_name="test")

        inner = MockLLMClient()
        inner.complete = AsyncMock(return_value=CompletionResult.fail(error="rate_limited"))
        client = InstrumentedLLMClient(client=inner, run_logger=logger)

        result = await client.complete(messages=[Message.user("Hello")])

        assert result.success is False
        record = logger.get_current_record()
        assert record is not None
        assert len(record.llm_calls) == 1
        assert record.llm_calls[0].output == ""

    @pytest.mark.asyncio
    async def test_no_active_run_does_not_crash(self) -> None:
        """If no run is active in RunLogger, complete() must still work (no crash)."""
        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        inner = MockLLMClient()
        client = InstrumentedLLMClient(client=inner, run_logger=logger)

        result = await client.complete(messages=[Message.user("Hello")])
        assert result.success is True

    def test_count_tokens_delegates(self) -> None:
        """Token counting must delegate to inner client."""
        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        inner = MockLLMClient()
        client = InstrumentedLLMClient(client=inner, run_logger=logger)

        direct = inner.count_tokens(text="hello world")
        wrapped = client.count_tokens(text="hello world")
        assert wrapped == direct

    @pytest.mark.asyncio
    async def test_multiple_calls_all_recorded(self) -> None:
        """Multiple complete() calls must all appear in the RunRecord."""
        from cemaf.llm.instrumented import InstrumentedLLMClient
        from cemaf.llm.mock import MockLLMClient

        logger = InMemoryRunLogger()
        logger.start_run(run_id="test-run", dag_name="test")

        inner = MockLLMClient()
        client = InstrumentedLLMClient(client=inner, run_logger=logger)

        await client.complete(messages=[Message.user("First")])
        await client.complete(messages=[Message.user("Second")])
        await client.complete(messages=[Message.user("Third")])

        record = logger.get_current_record()
        assert record is not None
        assert len(record.llm_calls) == 3
