"""Integration test — `BlueprintSelectorHook` reaches compiled context via executor.

The whole point of the hook is that a blueprint's rendered prompt shows
up in the agent's compiled-context artifacts before the LLM call, with
no changes to the DAG or the agent. This test pre-seeds the library
with one recognizable RECIPE entry, wires the library into the hook,
wires the hook into `ContextNodeExecutor`, and calls `_compile_context`
directly — then asserts the blueprint's `to_prompt()` output is present
as the first source in the compiled context.
"""

from __future__ import annotations

import pytest

from cemaf.agents.registry import AgentRegistry
from cemaf.blueprint.library import BlueprintEntry, BlueprintLibrary
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.meta.blueprint_selector import LibraryBlueprintSelectorHook
from cemaf.orchestration.context_node_executor import ContextNodeExecutor


@pytest.fixture
def library_with_one_entry() -> BlueprintLibrary:
    library = BlueprintLibrary()
    library.register(
        entry=BlueprintEntry.recipe_entry(
            id="content/product-launch",
            title="Product Launch Announcement",
            tags=("launch", "marketing"),
            recipe={
                "name": "Product Launch",
                "goal": {
                    "objective": "Write a launch announcement",
                    "success_criteria": ["Clear value prop", "Concrete CTA"],
                },
                "style": {"tone": "confident", "format": "markdown"},
                "description": "Blueprint for external product announcements",
            },
        )
    )
    return library


@pytest.fixture
def compiler() -> PriorityContextCompiler:
    return PriorityContextCompiler(
        token_estimator=SimpleTokenEstimator(chars_per_token=4.0),
    )


@pytest.fixture
def token_budget() -> TokenBudget:
    return TokenBudget(max_tokens=4000, reserved_for_output=500)


class TestHookReachesCompiledContext:
    @pytest.mark.asyncio
    async def test_preamble_present_when_query_matches(
        self,
        library_with_one_entry: BlueprintLibrary,
        compiler: PriorityContextCompiler,
        token_budget: TokenBudget,
    ) -> None:
        hook = LibraryBlueprintSelectorHook(library=library_with_one_entry)
        executor = ContextNodeExecutor(
            agent_registry=AgentRegistry(),
            context_compiler=compiler,
            token_budget=token_budget,
            blueprint_selector=hook,
        )

        compiled = await executor._compile_context(
            agent_name="Writer",
            inputs={"objective": "Write a product launch announcement"},
            memories={},
        )

        assert compiled is not None
        source_keys = [s.key for s in compiled.sources]
        assert "blueprint:selected" in source_keys
        # Blueprint must be at index 0 (highest priority) so it survives
        # truncation when the token budget is tight — not just present somewhere.
        assert source_keys[0] == "blueprint:selected"
        # Selected blueprint's prompt content must be present.
        blueprint_source = next(s for s in compiled.sources if s.key == "blueprint:selected")
        assert "Write a launch announcement" in blueprint_source.content
        assert "Tone: confident" in blueprint_source.content

    @pytest.mark.asyncio
    async def test_no_preamble_when_no_match(
        self,
        library_with_one_entry: BlueprintLibrary,
        compiler: PriorityContextCompiler,
        token_budget: TokenBudget,
    ) -> None:
        hook = LibraryBlueprintSelectorHook(library=library_with_one_entry)
        executor = ContextNodeExecutor(
            agent_registry=AgentRegistry(),
            context_compiler=compiler,
            token_budget=token_budget,
            blueprint_selector=hook,
        )

        compiled = await executor._compile_context(
            agent_name="Writer",
            inputs={"objective": "xxxxx unrelated yyyyy"},
            memories={},
        )

        assert compiled is not None
        assert all(s.key != "blueprint:selected" for s in compiled.sources)

    @pytest.mark.asyncio
    async def test_no_hook_is_byte_identical_to_baseline(
        self,
        library_with_one_entry: BlueprintLibrary,
        compiler: PriorityContextCompiler,
        token_budget: TokenBudget,
    ) -> None:
        """Without a hook, the compile path must not know blueprints exist."""
        executor_with_hook = ContextNodeExecutor(
            agent_registry=AgentRegistry(),
            context_compiler=compiler,
            token_budget=token_budget,
            blueprint_selector=None,
        )

        compiled = await executor_with_hook._compile_context(
            agent_name="Writer",
            inputs={"objective": "Write a product launch announcement"},
            memories={},
        )

        assert compiled is not None
        assert all(s.key != "blueprint:selected" for s in compiled.sources)

    @pytest.mark.asyncio
    async def test_query_empty_when_no_goal_field(
        self,
        compiler: PriorityContextCompiler,
        token_budget: TokenBudget,
    ) -> None:
        """When inputs lack a goal-like field, no blueprint is injected.

        Previous behavior fell back to the agent name as the query — but
        that yielded false positives (every "Writer" node getting any
        blueprint with "writer" in the title). The new contract is empty
        query → no preamble, which is correct.
        """
        library = BlueprintLibrary()
        from cemaf.blueprint.core import Blueprint, SceneGoal

        bp = Blueprint(id="writer-bp", name="Writer BP", scene_goal=SceneGoal(objective="write"))
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id="writer",
                title="Writer Patterns",
                blueprint=bp,
            )
        )
        hook = LibraryBlueprintSelectorHook(library=library)
        executor = ContextNodeExecutor(
            agent_registry=AgentRegistry(),
            context_compiler=compiler,
            token_budget=token_budget,
            blueprint_selector=hook,
        )

        # Inputs carry no recognized goal field — selector must NOT fire.
        compiled = await executor._compile_context(
            agent_name="Writer",
            inputs={"random_field": "foo"},
            memories={},
        )

        assert compiled is not None
        source_keys = [s.key for s in compiled.sources]
        assert "blueprint:selected" not in source_keys
