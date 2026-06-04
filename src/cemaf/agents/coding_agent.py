"""CodingAgent — a spec→working-code loop on the coding skill kit.

The keystone of the autonomous SDLC: given a spec, the agent drives an LLM
tool-use loop over the coding skills (write/read/edit/list/shell/run_tests),
iterating until the project's tests pass or a turn/budget bound is hit.

Polyglot by construction — the agent never hard-codes a language; it writes
whatever the spec asks and verifies with RunTestsSkill's auto-detection.

Composition (no reinvention):
- `cemaf.skills.coding.*` — the agent's hands (this is what it calls)
- `cemaf.llm.protocols.LLMClient` — the reasoning engine (inject Opus/Sonnet/
  Haiku/Ollama; a tiered ModelRouter is a drop-in LLMClient)
- `cemaf.agents.base.Agent` — the ABC contract (id/skills/run)
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.core.enums import AgentStatus
from cemaf.core.types import AgentID
from cemaf.llm.protocols import LLMClient, Message, ToolCall, ToolDefinition
from cemaf.sandbox.shell import ShellSandbox
from cemaf.skills.base import Skill, SkillContext
from cemaf.skills.coding import (
    EditFileInput,
    EditFileSkill,
    ListDirInput,
    ListDirSkill,
    ReadFileInput,
    ReadFileSkill,
    RunTestsInput,
    RunTestsSkill,
    ShellInput,
    ShellSkill,
    WriteFileInput,
    WriteFileSkill,
)

DEFAULT_MAX_TURNS = 20
MAX_BARREN_TURNS = 3

_SYSTEM_PROMPT = """You are a senior software engineer working inside a sandboxed \
workspace. You are given a spec and must produce working, tested code.

Loop until the project's tests pass:
1. Write the source files the spec requires.
2. Write tests that cover the spec's acceptance criteria.
3. Use run_tests to execute the suite. Read failures from stderr.
4. Edit files to fix failures. Re-run tests.
5. When tests pass, call `done` with a one-line summary.

Rules:
- Use the tools; do not describe what you would do — do it.
- Implement the spec's invariants and acceptance criteria faithfully.
- Pick the language/toolchain the spec asks for; the test runner auto-detects it.
- If a dependency install or test command fails, read the error and adapt.
- Keep changes minimal and idiomatic. Do not invent files the spec does not need.
- You have a limited number of turns — be efficient, batch file writes early.
"""


class CodingGoal(BaseModel):
    """Input goal for the coding agent."""

    spec: str
    max_turns: int = DEFAULT_MAX_TURNS


class CodingResult(BaseModel):
    """Outcome of a coding run."""

    model_config = {"frozen": True}

    done: bool
    tests_passed: bool
    summary: str = ""
    turns_used: int = 0
    files: tuple[str, ...] = Field(default_factory=tuple)


def _tool_defs() -> list[ToolDefinition]:
    """LLM-facing tool schemas mirroring the coding skill kit + a `done` sentinel."""
    obj = "object"
    return [
        ToolDefinition(
            name="write_file",
            description="Create or overwrite a file at a workspace-relative path.",
            parameters={
                "type": obj,
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            },
            required=("path", "content"),
        ),
        ToolDefinition(
            name="read_file",
            description="Read a workspace-relative file.",
            parameters={"type": obj, "properties": {"path": {"type": "string"}}},
            required=("path",),
        ),
        ToolDefinition(
            name="edit_file",
            description="Replace an exact substring in a workspace file.",
            parameters={
                "type": obj,
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
            },
            required=("path", "old", "new"),
        ),
        ToolDefinition(
            name="list_dir",
            description="List files in the workspace (recursive, relative paths).",
            parameters={"type": obj, "properties": {"path": {"type": "string"}}},
            required=(),
        ),
        ToolDefinition(
            name="shell",
            description="Run a shell command in the sandbox (e.g. install deps, scaffold).",
            parameters={"type": obj, "properties": {"command": {"type": "string"}}},
            required=("command",),
        ),
        ToolDefinition(
            name="run_tests",
            description="Auto-detect the project's test command and run the suite.",
            parameters={"type": obj, "properties": {}},
            required=(),
        ),
        ToolDefinition(
            name="done",
            description="Signal completion. Call only after run_tests passed.",
            parameters={"type": obj, "properties": {"summary": {"type": "string"}}},
            required=("summary",),
        ),
    ]


class CodingAgent(Agent[CodingGoal, CodingResult]):
    """Drives an LLM tool-use loop over the coding skills until tests pass."""

    def __init__(self, *, llm: LLMClient, sandbox: ShellSandbox) -> None:
        self._llm = llm
        self._sandbox = sandbox
        root = sandbox.root
        self._write = WriteFileSkill(workspace=root)
        self._read = ReadFileSkill(workspace=root)
        self._edit = EditFileSkill(workspace=root)
        self._list = ListDirSkill(workspace=root)
        self._shell = ShellSkill(sandbox=sandbox)
        self._tests = RunTestsSkill(sandbox=sandbox)

    @property
    def id(self) -> AgentID:
        return AgentID("coding_agent")

    @property
    def description(self) -> str:
        return "Implements a spec as working, tested code via an iterative tool-use loop."

    @property
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        return (self._write, self._read, self._edit, self._list, self._shell, self._tests)

    async def run(self, goal: CodingGoal, context: AgentContext) -> AgentResult[CodingResult]:
        await self._sandbox.setup()
        skill_ctx = SkillContext(run_id=context.run_id, agent_id=str(self.id))
        tools = _tool_defs()
        messages: list[Message] = [
            Message.system(_SYSTEM_PROMPT),
            Message.user(f"Spec:\n\n{goal.spec}"),
        ]

        tests_passed = False
        barren_turns = 0
        for turn in range(1, goal.max_turns + 1):
            completion = await self._llm.complete(messages=messages, tools=tools)
            if not completion.success or completion.message is None:
                return AgentResult.fail(
                    f"llm error on turn {turn}: {completion.error}",
                    AgentState(status=AgentStatus.FAILED, iteration=turn),
                )

            assistant = completion.message
            messages.append(assistant)
            calls = completion.tool_calls
            if not calls:
                # No tool call — nudge, but bail if the model stalls for MAX_BARREN_TURNS in a row.
                barren_turns += 1
                if barren_turns >= MAX_BARREN_TURNS:
                    state = AgentState(status=AgentStatus.FAILED, iteration=turn)
                    return AgentResult.ok(
                        CodingResult(
                            done=False,
                            tests_passed=tests_passed,
                            summary=f"stalled: no tool calls for {barren_turns} turns",
                            turns_used=turn,
                            files=await self._list_files(ctx=skill_ctx),
                        ),
                        state,
                    )
                messages.append(Message.user("Use a tool to make progress, or call done when tests pass."))
                continue
            barren_turns = 0

            done_summary: str | None = None
            for call in calls:
                if call.name == "done":
                    done_summary = self._args(call).get("summary", "")
                    continue
                # A skill that raises must not kill the loop — feed the error back so the
                # model can adapt, exactly as it would for a returned skill failure.
                try:
                    result_text, passed = await self._dispatch(call=call, ctx=skill_ctx)
                except Exception as exc:  # noqa: BLE001 - deliberately broad: never crash the loop
                    result_text, passed = (f"ERROR: {call.name} raised: {exc}", None)
                if passed is not None:
                    tests_passed = passed
                messages.append(
                    Message.tool_result(tool_call_id=call.id, content=result_text, name=call.name)
                )

            if done_summary is not None:
                files = await self._list_files(ctx=skill_ctx)
                state = AgentState(status=AgentStatus.COMPLETED, iteration=turn)
                return AgentResult.ok(
                    CodingResult(
                        done=True,
                        tests_passed=tests_passed,
                        summary=done_summary,
                        turns_used=turn,
                        files=files,
                    ),
                    state,
                )

        files = await self._list_files(ctx=skill_ctx)
        state = AgentState(status=AgentStatus.FAILED, iteration=goal.max_turns)
        return AgentResult.ok(
            CodingResult(
                done=False,
                tests_passed=tests_passed,
                summary="turn budget exhausted without calling done",
                turns_used=goal.max_turns,
                files=files,
            ),
            state,
        )

    @staticmethod
    def _args(call: ToolCall) -> dict[str, Any]:
        """Parse a tool call's arguments to a dict, tolerating str-JSON or malformed input."""
        args = call.arguments
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return dict(args) if isinstance(args, dict) else {}

    async def _dispatch(self, *, call: ToolCall, ctx: SkillContext) -> tuple[str, bool | None]:
        """Run one tool call. Returns (text_for_llm, tests_passed_or_None)."""
        args = self._args(call)
        name = call.name
        if name == "write_file":
            r = await self._write.execute(
                WriteFileInput(path=args.get("path", ""), content=args.get("content", "")), ctx
            )
            if not r.success or r.data is None:
                return (f"ERROR: {r.error}", None)
            return (f"wrote {r.data.data}", None)
        if name == "read_file":
            r = await self._read.execute(ReadFileInput(path=args.get("path", "")), ctx)
            if not r.success or r.data is None:
                return (f"ERROR: {r.error}", None)
            return (r.data.data, None)
        if name == "edit_file":
            edit_input = EditFileInput(
                path=args.get("path", ""), old=args.get("old", ""), new=args.get("new", "")
            )
            r = await self._edit.execute(edit_input, ctx)
            if not r.success or r.data is None:
                return (f"ERROR: {r.error}", None)
            return (f"edited {r.data.data}", None)
        if name == "list_dir":
            r = await self._list.execute(ListDirInput(path=args.get("path", ".")), ctx)
            if not r.success or r.data is None:
                return (f"ERROR: {r.error}", None)
            return ("\n".join(r.data.data), None)
        if name == "shell":
            r = await self._shell.execute(ShellInput(command=args.get("command", "")), ctx)
            if not r.success or r.data is None:
                return (f"ERROR: {r.error}", None)
            sr = r.data.data
            return (f"exit={sr.exit_code}\nstdout:\n{sr.stdout}\nstderr:\n{sr.stderr}", None)
        if name == "run_tests":
            r = await self._tests.execute(RunTestsInput(), ctx)
            if not r.success or r.data is None:
                return (f"ERROR: {r.error}", False)
            sr = r.data.data
            return (
                f"tests {'PASSED' if sr.success else 'FAILED'} (exit={sr.exit_code})\n"
                f"stdout:\n{sr.stdout}\nstderr:\n{sr.stderr}",
                sr.success,
            )
        return (f"ERROR: unknown tool {name}", None)

    async def _list_files(self, *, ctx: SkillContext) -> tuple[str, ...]:
        r = await self._list.execute(ListDirInput(), ctx)
        return tuple(r.data.data) if r.success and r.data is not None else ()
