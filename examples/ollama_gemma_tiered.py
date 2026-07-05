"""Tiered Gemma via Ollama — 4b for simple calls, 12b for complex ones.

Uses `cemaf.llm.ollama.create_tiered_ollama_router`, which escalates to the
large model when the prompt crosses a character threshold or uses tools.

Prereqs:
    brew install ollama && brew services start ollama
    ollama pull gemma3:4b
    ollama pull gemma3:12b

Usage:
    uv run python examples/ollama_gemma_tiered.py
"""

from __future__ import annotations

import asyncio

from cemaf.llm.factories import create_llm_client
from cemaf.llm.protocols import LLMClient, Message


async def ask(client: LLMClient, label: str, messages: list[Message]) -> None:
    result = await client.complete(messages=messages)
    if not result.success or result.message is None:
        print(f"[{label}] FAILED: {result.error}")
        return
    content = result.message.content
    text = content if isinstance(content, str) else str(content)
    print(f"[{label}] model={result.model} tokens={result.prompt_tokens}+{result.completion_tokens}")
    print(f"  → {text.strip()[:240]}\n")


async def _run(client: LLMClient) -> None:
    await ask(
        client=client,
        label="simple",
        messages=[Message.user(content="Say 'hello' in one word.")],
    )

    long_brief = (
        "You are coordinating four sub-agents (Librarian, Researcher, Summarizer, "
        "Writer) to produce a 500-word brief on local-first AI architectures. "
        "Outline the DAG you would run: nodes, dependencies, expected outputs, "
        "and where human-in-the-loop pauses go. Then list three failure modes "
        "of this pipeline and how you would detect each. Be specific, and "
        "include concrete span names, metric attributes, and example log events "
        "for every observability decision you recommend."
    )
    await ask(
        client=client,
        label="complex",
        messages=[
            Message.system(content="You are a senior AI systems architect."),
            Message.user(content=long_brief),
        ],
    )


async def smoke_main() -> None:
    from cemaf.llm.mock import MockLLMClient
    from cemaf.llm.model_router import ModelRoute, ModelRouter
    from cemaf.llm.ollama import CharBasedEstimator
    from cemaf.llm.protocols import LLMConfig

    small = MockLLMClient(responses=["hello"], config=LLMConfig(model="gemma3:4b"))
    large = MockLLMClient(
        responses=["Use a DAG with planning, retrieval, writing, review, and publish nodes."],
        config=LLMConfig(model="gemma3:12b"),
    )
    client = ModelRouter(
        routes=[
            ModelRoute(threshold=0.5, client=small, model_name="gemma3:4b"),
            ModelRoute(threshold=1.0, client=large, model_name="gemma3:12b"),
        ],
        estimator=CharBasedEstimator(escalation_chars=50),
    )
    await _run(client)


async def main() -> None:
    client = create_llm_client(provider="ollama-tiered")
    await _run(client)


if __name__ == "__main__":
    asyncio.run(main())
