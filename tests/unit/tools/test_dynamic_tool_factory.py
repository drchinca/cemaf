"""Security + behavior tests for DynamicToolFactory.

The factory compiles LLM-generated source and runs it in-process — a remote-code-
execution surface driven by model output. These tests pin the fail-closed default
and the explicit opt-in escape hatch.
"""

from __future__ import annotations

import pytest

from cemaf.llm.protocols import CompletionResult, Message
from cemaf.tools.dynamic import DynamicToolFactory, GeneratedToolSpec
from cemaf.tools.registry import ToolRegistry

_TOOL_SRC = "async def execute(**kwargs) -> dict:\n    return {'doubled': kwargs.get('n', 0) * 2}\n"


class _StubLLM:
    """Returns a fixed code blob; satisfies the slice of LLMClient the factory calls."""

    def __init__(self, code: str = _TOOL_SRC) -> None:
        self._code = code

    async def complete(self, messages: list[Message], *args: object, **kwargs: object) -> CompletionResult:
        return CompletionResult.ok(message=Message.assistant(self._code))


def _spec() -> GeneratedToolSpec:
    return GeneratedToolSpec(
        name="doubler",
        description="double a number",
        parameters={"n": {"type": "integer"}},
        required=("n",),
    )


@pytest.mark.asyncio
async def test_registration_is_disabled_by_default() -> None:
    """Fail closed: without opt-in, no LLM code is compiled or run."""
    factory = DynamicToolFactory(llm_client=_StubLLM(), registry=ToolRegistry())

    result = await factory.generate_and_register(_spec())

    assert not result.success
    assert "disabled" in (result.error or "")


@pytest.mark.asyncio
async def test_build_tool_refuses_in_process_exec_when_not_opted_in() -> None:
    """Defense-in-depth: the private exec path itself refuses, not just the public entry."""
    factory = DynamicToolFactory(llm_client=_StubLLM(), registry=ToolRegistry())

    from cemaf.core.types import ToolID

    with pytest.raises(PermissionError, match="in-process exec"):
        factory._build_tool(ToolID("x"), _spec(), _TOOL_SRC)


@pytest.mark.asyncio
async def test_opt_in_registers_and_runs_tool() -> None:
    """With explicit opt-in, the generated tool compiles, registers, and executes."""
    registry = ToolRegistry()
    factory = DynamicToolFactory(
        llm_client=_StubLLM(),
        registry=registry,
        allow_in_process_exec=True,
    )

    result = await factory.generate_and_register(_spec())

    assert result.success, result.error
    tool_id = result.data.tool_id
    assert tool_id is not None
    tool = registry.get(tool_id)
    assert tool is not None

    exec_result = await tool.execute(n=21)
    assert exec_result.success
    assert exec_result.data == {"doubled": 42}


@pytest.mark.asyncio
async def test_syntax_error_in_generated_code_fails_cleanly() -> None:
    factory = DynamicToolFactory(
        llm_client=_StubLLM(code="async def execute(**kwargs) ->:\n  pass"),
        registry=ToolRegistry(),
        allow_in_process_exec=True,
    )

    result = await factory.generate_and_register(_spec())

    assert not result.success
    assert "Syntax error" in (result.error or "")
