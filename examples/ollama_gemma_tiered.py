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
import os

from cemaf.llm.factories import create_llm_client


def smoke_skip_reason() -> str | None:
    """Runs when an Ollama daemon is reachable; skips with a reason when it isn't."""
    import urllib.error
    import urllib.request

    host = os.environ.get("CEMAF_OLLAMA_HOST", "http://localhost:11434")
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=1.0)
    except (urllib.error.URLError, OSError):
        return f"Ollama not reachable at {host} (start it to run this example)"
    return None
from cemaf.llm.protocols import LLMClient, Message


async def ask(client: LLMClient, label: str, messages: list[Message]) -> None:
    result = await client.complete(messages=messages)
    if not result.success or result.message is None:
        print(f"[{label}] FAILED: {result.error}")
        return
    content = result.message.content
    text = content if isinstance(content, str) else str(content)
    print(f"[{label}] model={result.model} "
          f"tokens={result.prompt_tokens}+{result.completion_tokens}")
    print(f"  → {text.strip()[:240]}\n")


async def main() -> None:
    client = create_llm_client(provider="ollama-tiered")

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


if __name__ == "__main__":
    asyncio.run(main())
