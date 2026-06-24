"""Tests for LLM factory helpers."""

from cemaf.llm.factories import create_instrumented_client
from cemaf.llm.mock import MockLLMClient
from cemaf.observability.run_logger import InMemoryRunLogger


def test_create_instrumented_client_wraps_client() -> None:
    inner = MockLLMClient(responses=["ok"])
    logger = InMemoryRunLogger()

    wrapped = create_instrumented_client(
        client=inner,
        run_logger=logger,
        node_id="writer",
        agent_id="writer",
    )

    assert wrapped.config.model == inner.config.model
