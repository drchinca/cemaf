"""Integration test: cemaf.iteration.IterationLoop → real ShellSandbox + RunTestsSkill.

Proves the failure-feedback loop (SPEC-08) is a live seam, not a dead end: a real
`RunTestsSkill` runs a real command inside a real `ShellSandbox`, the resulting
`ShellResult` flows through a real parser into a `FailureSignal`, and the loop
re-attempts until the verifier passes.

We avoid nesting `uv run pytest` inside the outer pytest run (which corrupts the
event loop / nested-uv env, per the note in tests/unit/skills/coding). Instead the
"attempt" writes a sentinel file and the "verify" runs a real shell script in the
sandbox that exits non-zero until the sentinel exists — exercising the full
attempt → sandbox-exec → parse → re-attempt cycle with no mocks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cemaf.core.result import Result
from cemaf.iteration.loop import IterationLoop
from cemaf.iteration.parsers import PytestParser, RuffParser, ShellFallbackParser
from cemaf.iteration.types import FailureKind, FailureSignal, IterationLimits, IterationOutcome
from cemaf.sandbox.shell import NetworkPolicy, ShellResult, ShellSandbox, ShellSandboxConfig
from cemaf.skills.base import SkillContext
from cemaf.skills.coding.tests import RunTestsInput, RunTestsSkill


@pytest.fixture
def sandbox(tmp_path: Path) -> ShellSandbox:
    return ShellSandbox(config=ShellSandboxConfig(root=tmp_path, network=NetworkPolicy.ALLOW))


@pytest.mark.asyncio
async def test_loop_converges_via_real_sandbox(sandbox: ShellSandbox) -> None:
    """A real sandbox verifier fails on attempt 1, the loop re-attempts, attempt 2 passes."""
    await sandbox.setup()
    # A real Makefile whose `test` target fails until `fixed` exists — RunTestsSkill
    # auto-detects the Makefile and runs `make test` in the sandbox.
    (sandbox.root / "Makefile").write_text(
        "test:\n\t@test -f fixed && echo ok || (echo 'FAILED: fixed missing' >&2; exit 1)\n"
    )
    skill = RunTestsSkill(sandbox=sandbox)
    ctx = SkillContext(run_id="run-1", agent_id="coder")

    state = {"attempt": 0}

    async def attempt(signal: FailureSignal | None) -> Result[Any]:
        state["attempt"] += 1
        # First attempt does nothing (test will fail); second attempt "fixes" the code.
        if signal is not None:
            (sandbox.root / "fixed").write_text("done")
        return Result.ok(data={"attempt": state["attempt"]}, metadata={"cost_usd": 0.0})

    async def verify(_: Result[Any]) -> ShellResult:
        skill_result = await skill.execute(RunTestsInput(), ctx)
        # RunTestsSkill wraps ShellResult in SkillOutput(data=...).
        return skill_result.data.data

    loop = IterationLoop(
        attempt=attempt,
        verify=verify,
        parsers=(PytestParser(), RuffParser(), ShellFallbackParser()),
        limits=IterationLimits(max_attempts=4, max_cost_usd=10.0),
    )
    report = await loop.run()

    assert report.outcome is IterationOutcome.SUCCESS
    assert report.attempts == 2
    # the second attempt received a real FailureSignal parsed from the sandbox failure
    assert state["attempt"] == 2


@pytest.mark.asyncio
async def test_loop_exhausts_when_never_fixed(sandbox: ShellSandbox) -> None:
    """A verifier that always fails drives the loop to EXHAUSTED with a real last_signal."""
    await sandbox.setup()
    (sandbox.root / "Makefile").write_text("test:\n\t@echo 'FAILED: always' >&2; exit 1\n")
    skill = RunTestsSkill(sandbox=sandbox)
    ctx = SkillContext(run_id="run-2", agent_id="coder")

    async def attempt(_: FailureSignal | None) -> Result[Any]:
        return Result.ok(data={}, metadata={"cost_usd": 0.0})

    async def verify(_: Result[Any]) -> ShellResult:
        return (await skill.execute(RunTestsInput(), ctx)).data.data

    loop = IterationLoop(
        attempt=attempt,
        verify=verify,
        parsers=(ShellFallbackParser(),),
        limits=IterationLimits(max_attempts=3, max_cost_usd=10.0),
    )
    report = await loop.run()

    assert report.outcome is IterationOutcome.EXHAUSTED
    assert report.attempts == 3
    assert report.last_signal is not None
    assert report.last_signal.kind is FailureKind.UNKNOWN
    assert "always" in report.last_signal.summary
