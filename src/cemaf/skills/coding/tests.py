"""RunTestsSkill — language-detecting test runner over the sandbox.

Detects the project's ecosystem from marker files and runs the right test
command, so one agent loop verifies Python, TypeScript/JS, Go, Rust, or
JVM/Gradle code without the caller hard-coding pytest.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from cemaf.core.result import Result
from cemaf.core.types import SkillID
from cemaf.sandbox.shell import SandboxViolation, ShellResult, ShellSandbox
from cemaf.skills.base import Skill, SkillContext, SkillOutput, SkillResult
from cemaf.tools.base import Tool

# (marker file, test command) — order matters: first matching marker wins.
_DETECTORS: tuple[tuple[str, list[str]], ...] = (
    ("pyproject.toml", ["uv", "run", "pytest", "-q"]),
    ("pytest.ini", ["uv", "run", "pytest", "-q"]),
    ("setup.cfg", ["uv", "run", "pytest", "-q"]),
    ("go.mod", ["go", "test", "./..."]),
    ("Cargo.toml", ["cargo", "test"]),
    ("build.gradle", ["gradle", "test"]),
    ("build.gradle.kts", ["gradle", "test"]),
    ("pom.xml", ["mvn", "test"]),
    ("package.json", ["npm", "test"]),  # JS/TS — package.json is common
    ("Makefile", ["make", "test"]),  # generic polyglot fallback — checked last
)


def detect_test_command(workspace: Path) -> list[str] | None:
    """Return the test command for the project in ``workspace``, or None if unknown."""
    for marker, command in _DETECTORS:
        if (workspace / marker).is_file():
            return command
    return None


class RunTestsInput(BaseModel):
    # Optional explicit override; when None the skill auto-detects from markers.
    command: list[str] | None = None
    cwd: str | None = None
    timeout_seconds: float | None = None


class RunTestsSkill(Skill[RunTestsInput, ShellResult]):
    """Detect the project's test command and run it in the sandbox."""

    def __init__(self, *, sandbox: ShellSandbox) -> None:
        self._sandbox = sandbox

    @property
    def id(self) -> SkillID:
        return SkillID("run_tests")

    @property
    def description(self) -> str:
        return "Detect the project language and run its test suite in the sandbox."

    @property
    def tools(self) -> tuple[Tool, ...]:
        return ()

    async def execute(self, input: RunTestsInput, context: SkillContext) -> SkillResult:
        command = input.command
        detected_from = "explicit"
        if command is None:
            base = self._sandbox.root if input.cwd is None else self._sandbox.root / input.cwd
            command = detect_test_command(base)
            detected_from = "auto"
            if command is None:
                return Result.fail(
                    "could not detect a test command — no known marker file "
                    "(pyproject.toml, package.json, go.mod, Cargo.toml, build.gradle, pom.xml, Makefile)"
                )
        try:
            result = await self._sandbox.run(
                command,
                cwd=input.cwd,
                timeout_seconds=input.timeout_seconds,
            )
        except SandboxViolation as exc:
            return Result.fail(f"sandbox policy: {exc}")
        return Result.ok(
            SkillOutput(data=result),
            metadata={
                "command": " ".join(command),
                "detected_from": detected_from,
                "passed": result.success,
                "exit_code": result.exit_code,
            },
        )
