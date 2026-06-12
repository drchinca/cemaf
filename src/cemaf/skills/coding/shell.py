"""ShellSkill — run a command in the agent's sandbox workspace."""

from __future__ import annotations

from pydantic import BaseModel

from cemaf.core.result import Result
from cemaf.core.types import SkillID
from cemaf.sandbox.shell import SandboxViolation, ShellResult, ShellSandbox
from cemaf.skills.base import Skill, SkillContext, SkillOutput, SkillResult
from cemaf.tools.base import Tool


class ShellInput(BaseModel):
    command: str | list[str]
    cwd: str | None = None
    timeout_seconds: float | None = None


class ShellSkill(Skill[ShellInput, ShellResult]):
    """Execute a shell command inside the sandbox (any toolchain)."""

    def __init__(self, *, sandbox: ShellSandbox) -> None:
        self._sandbox = sandbox

    @property
    def id(self) -> SkillID:
        return SkillID("shell")

    @property
    def description(self) -> str:
        return "Run a shell command in the sandbox workspace and return its result."

    @property
    def tools(self) -> tuple[Tool, ...]:
        return ()

    async def execute(self, input: ShellInput, context: SkillContext) -> SkillResult:
        try:
            result = await self._sandbox.run(
                input.command,
                cwd=input.cwd,
                timeout_seconds=input.timeout_seconds,
            )
        except SandboxViolation as exc:
            return Result.fail(f"sandbox policy: {exc}")
        meta = {
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_ms": result.duration_ms,
        }
        if result.success:
            return Result.ok(SkillOutput(data=result), metadata=meta)
        # A non-zero exit is a legitimate observable outcome, not a skill error —
        # return ok so the agent can read stderr and decide what to do next.
        return Result.ok(SkillOutput(data=result), metadata=meta)
