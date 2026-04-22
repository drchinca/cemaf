"""Tests for MetaSpecifier agent — fake LLMClient, fake runtime, real workspace."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cemaf.agents.base import AgentContext
from cemaf.core.types import TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
)
from cemaf.mcp.bridges.openspec.protocols import SubprocessResult
from cemaf.mcp.bridges.openspec.runtime import FakeOpenSpecRuntime
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.meta.goals import ProposalDoc, SpecGoal, SpecResult
from cemaf.meta.specifier import MetaSpecifier


class ScriptedLLM(LLMClient):
    """Fake LLMClient returning canned CompletionResults in order."""

    def __init__(self, *, responses: list[str], model: str = "fake-model") -> None:
        self._iter: Iterator[str] = iter(responses)
        self._config = LLMConfig(model=model)
        self.calls: list[list[Message]] = []

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: object | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        self.calls.append(messages)
        try:
            raw = next(self._iter)
        except StopIteration:
            return CompletionResult(
                success=False,
                error="ScriptedLLM exhausted",
                prompt_tokens=TokenCount(0),
                completion_tokens=TokenCount(0),
                total_tokens=TokenCount(0),
            )
        return CompletionResult.ok(message=Message(role=MessageRole.ASSISTANT, content=raw))

    async def stream(self, *args, **kwargs):  # pragma: no cover - unused
        raise NotImplementedError


def _valid_proposal_json(change_id: str = "add-foo") -> str:
    doc = ProposalDoc(
        change_id=change_id,
        title="Add Foo",
        why="We need foo.",
        what_changes=("Add foo",),
        impact=("affects: foo",),
        tasks=("implement foo",),
        deltas=(
            {
                "capability": "foo",
                "added_requirements": (
                    {
                        "name": "Foo works",
                        "statement": "The system SHALL provide foo.",
                        "scenarios": (
                            {
                                "name": "happy",
                                "given": ("setup done",),
                                "when": ("triggered",),
                                "then": ("foo done",),
                            },
                        ),
                    },
                ),
            },
        ),
    )
    return doc.model_dump_json()


def _agent_context() -> AgentContext:
    return AgentContext(run_id="run-1", agent_id="MetaSpecifier")


@pytest.fixture
def workspace(tmp_path: Path) -> OpenSpecWorkspace:
    return OpenSpecWorkspace(root=tmp_path / "openspec")


@pytest.mark.asyncio
async def test_specifier_without_llm_uses_template_and_passes_validation(
    workspace: OpenSpecWorkspace,
) -> None:
    runtime = FakeOpenSpecRuntime()
    runtime.register_result(("validate",), SubprocessResult(returncode=0, stdout=b"", stderr=b""))
    agent = MetaSpecifier(workspace=workspace, runtime=runtime, llm_client=None)
    result = await agent.run(
        goal=SpecGoal(
            feature_description="add thing",
            change_id="add-thing",
            capabilities=("thing",),
        ),
        context=_agent_context(),
    )
    assert result.success
    spec_result: SpecResult = result.output  # type: ignore[assignment]
    assert spec_result.validation_passed is True
    assert "proposal.md" in spec_result.rendered_files
    assert (workspace.changes_dir / "add-thing" / "proposal.md").exists()


@pytest.mark.asyncio
async def test_specifier_with_llm_parses_json_output(workspace: OpenSpecWorkspace) -> None:
    runtime = FakeOpenSpecRuntime()
    runtime.register_result(("validate",), SubprocessResult(returncode=0, stdout=b"", stderr=b""))
    llm = ScriptedLLM(responses=[_valid_proposal_json("add-foo")])
    agent = MetaSpecifier(workspace=workspace, runtime=runtime, llm_client=llm)
    result = await agent.run(
        goal=SpecGoal(
            feature_description="add foo",
            change_id="add-foo",
            capabilities=("foo",),
        ),
        context=_agent_context(),
    )
    assert result.success
    assert result.output.proposal.title == "Add Foo"  # type: ignore[union-attr]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_specifier_handles_fenced_json(workspace: OpenSpecWorkspace) -> None:
    runtime = FakeOpenSpecRuntime()
    runtime.register_result(("validate",), SubprocessResult(returncode=0, stdout=b"", stderr=b""))
    fenced = "```json\n" + _valid_proposal_json("add-fence") + "\n```"
    llm = ScriptedLLM(responses=[fenced])
    agent = MetaSpecifier(workspace=workspace, runtime=runtime, llm_client=llm)
    result = await agent.run(
        goal=SpecGoal(
            feature_description="x",
            change_id="add-fence",
            capabilities=("foo",),
        ),
        context=_agent_context(),
    )
    assert result.success


@pytest.mark.asyncio
async def test_specifier_fails_on_invalid_llm_json(workspace: OpenSpecWorkspace) -> None:
    runtime = FakeOpenSpecRuntime()
    llm = ScriptedLLM(responses=["this is not json"])
    agent = MetaSpecifier(workspace=workspace, runtime=runtime, llm_client=llm)
    result = await agent.run(
        goal=SpecGoal(feature_description="x", change_id="bad", capabilities=("foo",)),
        context=_agent_context(),
    )
    assert not result.success
    assert "JSON" in (result.error or "")


@pytest.mark.asyncio
async def test_specifier_runs_repair_once_then_gives_up(workspace: OpenSpecWorkspace) -> None:
    runtime = FakeOpenSpecRuntime()
    runtime.register_result(
        ("validate",),
        SubprocessResult(returncode=1, stdout=b"", stderr=b"error: missing scenario in specs/foo/spec.md\n"),
    )
    llm = ScriptedLLM(
        responses=[_valid_proposal_json("repair-me"), _valid_proposal_json("repair-me")],
    )
    agent = MetaSpecifier(workspace=workspace, runtime=runtime, llm_client=llm, max_repairs=1)
    result = await agent.run(
        goal=SpecGoal(feature_description="x", change_id="repair-me", capabilities=("foo",)),
        context=_agent_context(),
    )
    assert result.success
    spec_result: SpecResult = result.output  # type: ignore[assignment]
    assert spec_result.validation_passed is False
    # 1 authoring + 1 repair attempt = 2 LLM calls
    assert len(llm.calls) == 2
    # Diagnostics must surface — spec scenario explicitly requires it
    assert spec_result.diagnostics, "diagnostics must be non-empty on failure"
    error_diags = [d for d in spec_result.diagnostics if d["severity"] == "error"]
    assert error_diags, "at least one ERROR severity diagnostic expected"


@pytest.mark.asyncio
async def test_specifier_succeeds_after_repair(workspace: OpenSpecWorkspace) -> None:
    runtime = FakeOpenSpecRuntime()
    call_count = {"n": 0}

    def handler(args, cwd, stdin):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return SubprocessResult(returncode=1, stdout=b"", stderr=b"error: bad\n")
        return SubprocessResult(returncode=0, stdout=b"", stderr=b"")

    runtime.register(("validate",), handler)
    llm = ScriptedLLM(
        responses=[_valid_proposal_json("will-fix"), _valid_proposal_json("will-fix")],
    )
    agent = MetaSpecifier(workspace=workspace, runtime=runtime, llm_client=llm, max_repairs=2)
    result = await agent.run(
        goal=SpecGoal(feature_description="x", change_id="will-fix", capabilities=("foo",)),
        context=_agent_context(),
    )
    assert result.success
    assert result.output.validation_passed is True  # type: ignore[union-attr]
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_specifier_rejects_path_traversal_change_id(workspace: OpenSpecWorkspace) -> None:
    """Invariant: never writes outside the configured workspace root."""
    agent = MetaSpecifier(workspace=workspace, runtime=None, llm_client=None)
    result = await agent.run(
        goal=SpecGoal(
            feature_description="malicious",
            change_id="../escape",
            capabilities=("evil",),
        ),
        context=_agent_context(),
    )
    assert not result.success
    assert "Invalid change_id" in (result.error or "")


@pytest.mark.asyncio
async def test_specifier_without_runtime_reports_failed_validation(workspace: OpenSpecWorkspace) -> None:
    """Honest signal: with no runtime, we wrote files but cannot prove they validate."""
    agent = MetaSpecifier(workspace=workspace, runtime=None, llm_client=None)
    result = await agent.run(
        goal=SpecGoal(feature_description="x", change_id="no-runtime", capabilities=("foo",)),
        context=_agent_context(),
    )
    assert result.success
    spec_result: SpecResult = result.output  # type: ignore[assignment]
    assert spec_result.validation_passed is False
    diagnostic_codes = {d["code"] for d in spec_result.diagnostics}
    assert "runtime-missing" in diagnostic_codes
