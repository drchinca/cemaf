"""Contract tests for CodingAgent — the spec→working-code loop.

The LLM is a scripted fake (deterministic, no network, no $) that emits a fixed
sequence of tool calls. The skills + sandbox are REAL — so these tests prove the
loop actually writes files, runs commands, observes results, and terminates on
`done`. The real-model behavior is out of scope here (that's the dogfood run).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.agents import AgentContext, CodingAgent, CodingGoal
from cemaf.llm.protocols import CompletionResult, Message, ToolCall
from cemaf.sandbox import NetworkPolicy, ShellSandbox, ShellSandboxConfig

CTX = AgentContext(run_id="run-1", agent_id="coding_agent")


class ScriptedLLM:
    """Emits a pre-scripted list of (text, tool_calls) turns as CompletionResults."""

    def __init__(self, turns: list[list[ToolCall]]) -> None:
        self._turns = turns
        self._i = 0
        self.calls_seen: list[int] = []

    async def complete(self, messages, tools=None, config_override=None, **kw) -> CompletionResult:
        self.calls_seen.append(len(messages))
        if self._i >= len(self._turns):
            # default: stop with no tool calls
            return CompletionResult.ok(message=Message.assistant("(no more script)"))
        tool_calls = tuple(self._turns[self._i])
        self._i += 1
        return CompletionResult.ok(message=Message.assistant("", tool_calls=tool_calls))

    @property
    def config(self):  # pragma: no cover - unused by the agent
        from cemaf.llm.protocols import LLMConfig

        return LLMConfig(model="scripted")


def _sandbox(tmp_path: Path) -> ShellSandbox:
    return ShellSandbox(config=ShellSandboxConfig(root=tmp_path, network=NetworkPolicy.ALLOW))


@pytest.mark.asyncio
async def test_loop_writes_shells_and_completes(tmp_path: Path) -> None:
    """write_file -> shell -> done. Real skills, real sandbox.

    Uses shell (not run_tests) on purpose: it exercises the multi-tool loop end to
    end without nesting pytest-in-pytest. The real-pytest-in-sandbox path is covered
    by the integration suite, not here.
    """
    llm = ScriptedLLM(
        [
            [ToolCall(id="1", name="write_file", arguments={"path": "answer.txt", "content": "42"})],
            [ToolCall(id="2", name="shell", arguments={"command": "cat answer.txt"})],
            [ToolCall(id="3", name="done", arguments={"summary": "wrote answer.txt"})],
        ]
    )
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="Create answer.txt containing 42."), CTX)

    assert result.success
    assert result.output.done
    assert result.output.summary == "wrote answer.txt"
    assert "answer.txt" in result.output.files
    assert (tmp_path / "answer.txt").read_text() == "42"


@pytest.mark.asyncio
async def test_run_tests_failure_is_observed(tmp_path: Path) -> None:
    """An empty workspace has no test marker → run_tests reports failure → tests_passed False."""
    llm = ScriptedLLM(
        [
            [ToolCall(id="1", name="run_tests", arguments={})],
            [ToolCall(id="2", name="done", arguments={"summary": "attempted"})],
        ]
    )
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="x"), CTX)

    assert result.success
    assert result.output.done
    assert result.output.tests_passed is False  # no marker → run_tests failed to detect


@pytest.mark.asyncio
async def test_tests_passed_true_survives_to_done(tmp_path: Path) -> None:
    """A green suite on turn N sets tests_passed=True and it carries to a later done.

    Uses a Makefile `test:` target running `true` — RunTestsSkill auto-detects it and
    runs a trivially-green command, so we observe the real PASS path WITHOUT nesting pytest.
    """
    (tmp_path / "Makefile").write_text("test:\n\ttrue\n")
    llm = ScriptedLLM(
        [
            [ToolCall(id="1", name="run_tests", arguments={})],
            [ToolCall(id="2", name="write_file", arguments={"path": "note.txt", "content": "ok"})],
            [ToolCall(id="3", name="done", arguments={"summary": "green"})],
        ]
    )
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="ship it"), CTX)

    assert result.success
    assert result.output.done
    assert result.output.tests_passed is True


@pytest.mark.asyncio
async def test_read_list_and_unknown_tool_dispatch(tmp_path: Path) -> None:
    """read_file, list_dir, and an unknown tool all dispatch without crashing the loop."""
    (tmp_path / "seed.txt").write_text("hello")
    llm = ScriptedLLM(
        [
            [ToolCall(id="1", name="read_file", arguments={"path": "seed.txt"})],
            [ToolCall(id="2", name="list_dir", arguments={})],
            [ToolCall(id="3", name="frobnicate", arguments={"x": 1})],  # hallucinated tool
            [ToolCall(id="4", name="done", arguments={"summary": "explored"})],
        ]
    )
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="explore"), CTX)

    assert result.success
    assert result.output.done
    assert "seed.txt" in result.output.files


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_turn(tmp_path: Path) -> None:
    """A single turn emitting several write_file calls dispatches all of them in order."""
    llm = ScriptedLLM(
        [
            [
                ToolCall(id="1", name="write_file", arguments={"path": "a.txt", "content": "A"}),
                ToolCall(id="2", name="write_file", arguments={"path": "b.txt", "content": "B"}),
            ],
            [ToolCall(id="3", name="done", arguments={"summary": "wrote both"})],
        ]
    )
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="two files"), CTX)

    assert result.success
    assert (tmp_path / "a.txt").read_text() == "A"
    assert (tmp_path / "b.txt").read_text() == "B"
    assert result.output.turns_used == 2


@pytest.mark.asyncio
async def test_malformed_arguments_degrade_gracefully(tmp_path: Path) -> None:
    """Non-dict JSON in tool arguments must NOT raise — the loop reads the skill error and continues."""
    llm = ScriptedLLM(
        [
            # arguments as a JSON array string → _args returns {} → write_file gets empty path → skill error
            [ToolCall(id="1", name="write_file", arguments="[1, 2, 3]")],
            [ToolCall(id="2", name="done", arguments={"summary": "survived bad args"})],
        ]
    )
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="x"), CTX)

    assert result.success  # did not raise
    assert result.output.done


@pytest.mark.asyncio
async def test_stalls_after_max_barren_turns(tmp_path: Path) -> None:
    """Persistent no-tool-call turns bail at MAX_BARREN_TURNS instead of riding the full budget."""
    llm = ScriptedLLM([])  # always emits text, never a tool call
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="x", max_turns=50), CTX)

    assert result.success
    assert not result.output.done
    assert "stalled" in result.output.summary
    assert result.output.turns_used <= 3  # MAX_BARREN_TURNS, not 50


@pytest.mark.asyncio
async def test_turn_budget_exhaustion(tmp_path: Path) -> None:
    """If the agent never calls done, the loop stops at max_turns without hanging."""
    # script always writes, never done
    turns = [
        [ToolCall(id=str(i), name="write_file", arguments={"path": f"f{i}.txt", "content": "x"})]
        for i in range(10)
    ]
    llm = ScriptedLLM(turns)
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="loop forever", max_turns=3), CTX)

    assert result.success  # returns a result, doesn't raise
    assert not result.output.done
    assert result.output.turns_used == 3
    assert "budget exhausted" in result.output.summary


@pytest.mark.asyncio
async def test_no_tool_call_nudges_then_stops(tmp_path: Path) -> None:
    """A turn with no tool call gets nudged; persistent no-ops exhaust the budget."""
    llm = ScriptedLLM([])  # always "(no more script)" with no tool calls
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="x", max_turns=2), CTX)

    assert result.success
    assert not result.output.done


@pytest.mark.asyncio
async def test_llm_error_fails_cleanly(tmp_path: Path) -> None:
    class FailingLLM(ScriptedLLM):
        async def complete(self, messages, tools=None, config_override=None, **kw) -> CompletionResult:
            return CompletionResult.fail("model exploded")

    agent = CodingAgent(llm=FailingLLM([]), sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="x"), CTX)

    assert not result.success
    assert "model exploded" in result.error


@pytest.mark.asyncio
async def test_edit_after_write(tmp_path: Path) -> None:
    """write -> edit -> done; proves multi-step file mutation through the loop."""
    llm = ScriptedLLM(
        [
            [ToolCall(id="1", name="write_file", arguments={"path": "v.py", "content": "V = '0.1.0'\n"})],
            [ToolCall(id="2", name="edit_file", arguments={"path": "v.py", "old": "0.1.0", "new": "0.2.0"})],
            [ToolCall(id="3", name="done", arguments={"summary": "bumped"})],
        ]
    )
    agent = CodingAgent(llm=llm, sandbox=_sandbox(tmp_path))

    result = await agent.run(CodingGoal(spec="bump version"), CTX)

    assert result.success
    assert (tmp_path / "v.py").read_text() == "V = '0.2.0'\n"
