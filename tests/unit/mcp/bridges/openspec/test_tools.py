"""Tests for OpenSpec tools — backed by FakeOpenSpecRuntime, no patch() required."""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.mcp.bridges.openspec.protocols import SubprocessResult
from cemaf.mcp.bridges.openspec.runtime import FakeOpenSpecRuntime
from cemaf.mcp.bridges.openspec.tools import (
    OpenSpecDeleteChangeTool,
    OpenSpecListTool,
    OpenSpecShowTool,
    OpenSpecValidateTool,
    OpenSpecWriteChangeTool,
    create_openspec_tools,
)
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace


@pytest.fixture
def workspace(tmp_path: Path) -> OpenSpecWorkspace:
    return OpenSpecWorkspace(root=tmp_path / "openspec")


@pytest.fixture
def fake_runtime() -> FakeOpenSpecRuntime:
    return FakeOpenSpecRuntime()


@pytest.mark.asyncio
async def test_write_then_list_then_show(workspace: OpenSpecWorkspace) -> None:
    write_tool = OpenSpecWriteChangeTool(workspace=workspace)
    list_tool = OpenSpecListTool(workspace=workspace)
    show_tool = OpenSpecShowTool(workspace=workspace)

    write_result = await write_tool.execute(
        change_id="add-foo",
        files={"proposal.md": "# Why\n", "tasks.md": "- [ ] t\n"},
    )
    assert write_result.success
    assert write_result.data["change_id"] == "add-foo"

    list_result = await list_tool.execute()
    assert list_result.success
    assert list_result.data["changes"] == ["add-foo"]

    show_result = await show_tool.execute(change_id="add-foo")
    assert show_result.success
    assert show_result.data["files"]["proposal.md"] == "# Why\n"


@pytest.mark.asyncio
async def test_validate_tool_success_path(
    workspace: OpenSpecWorkspace,
    fake_runtime: FakeOpenSpecRuntime,
) -> None:
    fake_runtime.register_result(
        ("validate",),
        SubprocessResult(returncode=0, stdout=b"info: all good\n", stderr=b""),
    )
    validate_tool = OpenSpecValidateTool(runtime=fake_runtime, workspace=workspace)
    result = await validate_tool.execute(change_id="any", strict=True)
    assert result.success
    assert result.data["passed"] is True
    assert result.data["strict"] is True
    assert fake_runtime.calls[0][0] == ("validate", "any", "--strict")


@pytest.mark.asyncio
async def test_validate_tool_failure_returns_structured_report(
    workspace: OpenSpecWorkspace,
    fake_runtime: FakeOpenSpecRuntime,
) -> None:
    fake_runtime.register_result(
        ("validate",),
        SubprocessResult(
            returncode=1,
            stdout=b"",
            stderr=b"error: missing scenario in specs/x/spec.md\n",
        ),
    )
    validate_tool = OpenSpecValidateTool(runtime=fake_runtime, workspace=workspace)
    result = await validate_tool.execute(change_id="broken", strict=True)
    assert not result.success
    report = result.metadata["report"]
    assert report["exit_code"] == 1
    assert report["passed"] is False
    errors = [d for d in report["diagnostics"] if d["severity"] == "error"]
    assert len(errors) == 1
    assert errors[0]["path"] == "specs/x/spec.md"


@pytest.mark.asyncio
async def test_validate_without_strict_omits_flag(
    workspace: OpenSpecWorkspace,
    fake_runtime: FakeOpenSpecRuntime,
) -> None:
    fake_runtime.register_result(
        ("validate",),
        SubprocessResult(returncode=0, stdout=b"", stderr=b""),
    )
    validate_tool = OpenSpecValidateTool(runtime=fake_runtime, workspace=workspace)
    await validate_tool.execute(change_id="c", strict=False)
    assert fake_runtime.calls[0][0] == ("validate", "c")


@pytest.mark.asyncio
async def test_validate_missing_change_id_fails(
    workspace: OpenSpecWorkspace,
    fake_runtime: FakeOpenSpecRuntime,
) -> None:
    tool = OpenSpecValidateTool(runtime=fake_runtime, workspace=workspace)
    result = await tool.execute()
    assert not result.success
    assert "change_id" in (result.error or "")


@pytest.mark.asyncio
async def test_delete_tool_removes_change(workspace: OpenSpecWorkspace) -> None:
    write_tool = OpenSpecWriteChangeTool(workspace=workspace)
    delete_tool = OpenSpecDeleteChangeTool(workspace=workspace)
    await write_tool.execute(change_id="bye", files={"proposal.md": "x"})
    result = await delete_tool.execute(change_id="bye")
    assert result.success
    assert result.data["deleted"] is True


@pytest.mark.asyncio
async def test_show_missing_change_fails(workspace: OpenSpecWorkspace) -> None:
    tool = OpenSpecShowTool(workspace=workspace)
    result = await tool.execute(change_id="nope")
    assert not result.success


@pytest.mark.asyncio
async def test_write_rejects_empty_files(workspace: OpenSpecWorkspace) -> None:
    tool = OpenSpecWriteChangeTool(workspace=workspace)
    result = await tool.execute(change_id="c", files={})
    assert not result.success


@pytest.mark.asyncio
async def test_factory_returns_five_tools(
    workspace: OpenSpecWorkspace, fake_runtime: FakeOpenSpecRuntime
) -> None:
    tools = create_openspec_tools(runtime=fake_runtime, workspace=workspace)
    assert len(tools) == 5
    tool_ids = {str(t.id) for t in tools}
    assert tool_ids == {
        "openspec_validate",
        "openspec_list",
        "openspec_show",
        "openspec_write_change",
        "openspec_delete_change",
    }


@pytest.mark.asyncio
async def test_full_loop_write_then_validate(
    workspace: OpenSpecWorkspace, fake_runtime: FakeOpenSpecRuntime
) -> None:
    """Close the seam: write a proposal, then validate lands a structured report."""
    fake_runtime.register_result(
        ("validate",),
        SubprocessResult(returncode=0, stdout=b"info: ok\n", stderr=b""),
    )
    tools = create_openspec_tools(runtime=fake_runtime, workspace=workspace)
    by_id = {str(t.id): t for t in tools}

    written = await by_id["openspec_write_change"].execute(
        change_id="loop-1",
        files={
            "proposal.md": "# why\n",
            "tasks.md": "- [ ] x\n",
            "specs/x/spec.md": "## ADDED Requirements\n### Requirement: R\n#### Scenario: S\n",
        },
    )
    assert written.success

    validated = await by_id["openspec_validate"].execute(change_id="loop-1", strict=True)
    assert validated.success
    assert validated.data["change_id"] == "loop-1"
