"""Context layer: typed context sources compiled under a token budget.

Use-case: a prompt is assembled from layers of different kinds — a system prompt,
recalled memory, tool output, retrieved documents — each with a priority. When the
layers don't all fit the model's budget, the LOW-priority layers must be dropped,
not truncated blindly.

Best practice shown: model each layer as a typed `ContextSource` and let
`GreedySelectionAlgorithm` drop by priority under a `TokenBudget` — don't hand-roll
prompt-string slicing (see ../anti_patterns/README.md #1).

Usage:
    uv run python examples/context_layers/context_type_layers.py
"""

import asyncio

from cemaf.context.algorithm import GreedySelectionAlgorithm
from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource
from cemaf.core.types import TokenCount


async def main() -> None:
    # Four layers of distinct context types, each with an explicit token cost.
    layers = [
        ContextSource.from_system_prompt(
            "You are a support assistant.", token_count=TokenCount(20), priority=100
        ),
        ContextSource.from_memory(
            "User prefers concise answers.", "pref", token_count=TokenCount(15), priority=7
        ),
        ContextSource.from_tool_output(
            "search: 3 results found", "search", token_count=TokenCount(40), priority=5
        ),
        ContextSource.from_document(
            "Full policy manual ...", "policy_doc", token_count=TokenCount(80), priority=3
        ),
    ]
    # The greedy selector assumes priority-descending order.
    layers.sort(key=lambda s: s.priority, reverse=True)

    # Budget too small for everything (20+15+40+80 = 155 > 90 available).
    budget = TokenBudget(max_tokens=100, reserved_for_output=10)
    selection = GreedySelectionAlgorithm().select_sources(sources=layers, budget=budget)

    selected_ids = {s.key for s in selection.selected_sources}
    # Proof: the lowest-priority layer (the big document) is dropped; the
    # high-priority system + memory + tool layers survive.
    assert "policy_doc" in selection.excluded_keys
    assert selection.total_tokens <= budget.available_tokens
    assert {"system_prompt", "pref", "search"} <= selected_ids

    print(f"budget (available) : {budget.available_tokens} tokens")
    print("kept layers:")
    for source in selection.selected_sources:
        kind = source.context_type.value if source.context_type else source.source_type
        print(f"  {kind:<8} pri={source.priority:<4} {source.token_count} tok")
    print(f"dropped (over budget): {selection.excluded_keys}")


if __name__ == "__main__":
    asyncio.run(main())
