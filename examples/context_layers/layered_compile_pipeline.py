"""Context layer: the full compile pipeline — provenance in, budgeted prompt out.

Use-case: real context assembly is a pipeline. Raw inputs arrive from tools and
memory (each carrying provenance), land in an immutable Context, then get compiled
into a prompt that fits the model's token budget — dropping low-priority layers
when it must.

Best practice shown: the whole stack is CEMAF primitives — `ContextPatch`
(provenance) -> `Context` (immutable state) -> `PriorityContextCompiler` +
`TokenBudget` (budgeted prompt). No string concatenation, no manual trimming.

Usage:
    uv run python examples/context_layers/layered_compile_pipeline.py
"""

import asyncio

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch


async def main() -> None:
    # Layer 1 — provenance: each input enters as a patch that records WHO wrote it.
    retrieval_patch = ContextPatch.from_tool(
        tool_id="vector_search",
        path="policy_doc",
        value="Full refund policy: returns accepted within 30 days. " * 8,
        reason="retrieved for the user's refund question",
    )
    memory_patch = ContextPatch.from_tool(
        tool_id="memory_recall",
        path="user_pref",
        value="User prefers short answers.",
        reason="recalled session preference",
    )

    # Layer 2 — immutable Context: applying a patch returns a NEW context (lineage).
    context = Context()
    before_hash = context.state_hash()
    context = context.apply(retrieval_patch).apply(memory_patch)
    after_hash = context.state_hash()

    # Layer 3 — budgeted compile: prioritize the short preference over the big doc,
    # then squeeze into a small budget so the prompt stays within model limits.
    compiler = PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=4))
    budget = TokenBudget(max_tokens=120, reserved_for_output=20)
    compiled = await compiler.compile(
        artifacts=(("policy_doc", context.get("policy_doc")),),
        memories=(("user_pref", context.get("user_pref")),),
        budget=budget,
        priorities={"policy_doc": 3, "user_pref": 9},
    )

    messages = compiled.to_messages()
    # Proof: provenance changed the lineage, and the compiled prompt fits the budget.
    assert before_hash != after_hash
    assert compiled.within_budget()
    assert len(messages) >= 1

    print("provenance -> immutable context:")
    print(f"  lineage hash changed: {before_hash != after_hash}")
    print("budgeted compile:")
    print(f"  available budget : {budget.available_tokens} tokens")
    print(f"  compiled tokens  : {compiled.total_tokens}  (within budget: {compiled.within_budget()})")
    print(f"  layers in prompt : {[s.key for s in compiled.sources]}")
    print(f"  prompt messages  : {len(messages)}")


if __name__ == "__main__":
    asyncio.run(main())
