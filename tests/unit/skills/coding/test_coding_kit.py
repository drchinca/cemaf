"""Contract tests for the coding skill kit — real sandbox, real files, no mocks."""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.sandbox import NetworkPolicy, ShellSandbox, ShellSandboxConfig
from cemaf.skills.base import SkillContext
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
    detect_test_command,
)

CTX = SkillContext(run_id="run-1", agent_id="coder")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sandbox(workspace: Path) -> ShellSandbox:
    return ShellSandbox(config=ShellSandboxConfig(root=workspace, network=NetworkPolicy.ALLOW))


# ---- file ops --------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_then_read_roundtrip(workspace: Path) -> None:
    writer = WriteFileSkill(workspace=workspace)
    reader = ReadFileSkill(workspace=workspace)

    w = await writer.execute(WriteFileInput(path="src/app.py", content="x = 1\n"), CTX)
    r = await reader.execute(ReadFileInput(path="src/app.py"), CTX)

    assert w.success
    assert (workspace / "src/app.py").read_text() == "x = 1\n"
    assert r.success
    assert r.data.data == "x = 1\n"


@pytest.mark.asyncio
async def test_write_rejects_path_escape(workspace: Path) -> None:
    writer = WriteFileSkill(workspace=workspace)

    result = await writer.execute(WriteFileInput(path="../../evil.py", content="pwn"), CTX)

    assert not result.success
    assert "escapes workspace" in result.error


@pytest.mark.asyncio
async def test_read_missing_file_fails(workspace: Path) -> None:
    reader = ReadFileSkill(workspace=workspace)

    result = await reader.execute(ReadFileInput(path="nope.py"), CTX)

    assert not result.success
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_edit_replaces_exact_string(workspace: Path) -> None:
    writer = WriteFileSkill(workspace=workspace)
    editor = EditFileSkill(workspace=workspace)
    await writer.execute(WriteFileInput(path="m.py", content="version = '0.1.0'\n"), CTX)

    result = await editor.execute(EditFileInput(path="m.py", old="0.1.0", new="0.2.0", expect_count=1), CTX)

    assert result.success
    assert (workspace / "m.py").read_text() == "version = '0.2.0'\n"


@pytest.mark.asyncio
async def test_edit_missing_old_string_fails(workspace: Path) -> None:
    writer = WriteFileSkill(workspace=workspace)
    editor = EditFileSkill(workspace=workspace)
    await writer.execute(WriteFileInput(path="m.py", content="a = 1\n"), CTX)

    result = await editor.execute(EditFileInput(path="m.py", old="zzz", new="q"), CTX)

    assert not result.success
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_edit_count_mismatch_fails(workspace: Path) -> None:
    writer = WriteFileSkill(workspace=workspace)
    editor = EditFileSkill(workspace=workspace)
    await writer.execute(WriteFileInput(path="m.py", content="a a a\n"), CTX)

    result = await editor.execute(EditFileInput(path="m.py", old="a", new="b", expect_count=1), CTX)

    assert not result.success
    assert "found 3" in result.error


@pytest.mark.asyncio
async def test_list_dir_returns_relative_files(workspace: Path) -> None:
    writer = WriteFileSkill(workspace=workspace)
    lister = ListDirSkill(workspace=workspace)
    await writer.execute(WriteFileInput(path="src/a.py", content="1"), CTX)
    await writer.execute(WriteFileInput(path="tests/b.py", content="2"), CTX)

    result = await lister.execute(ListDirInput(), CTX)

    assert result.success
    assert set(result.data.data) == {"src/a.py", "tests/b.py"}


# ---- shell -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_shell_runs_command(sandbox: ShellSandbox) -> None:
    await sandbox.setup()
    skill = ShellSkill(sandbox=sandbox)

    result = await skill.execute(ShellInput(command=["echo", "hi"]), CTX)

    assert result.success
    assert result.data.data.stdout.strip() == "hi"


@pytest.mark.asyncio
async def test_shell_nonzero_exit_is_ok_result_with_failed_shellresult(sandbox: ShellSandbox) -> None:
    await sandbox.setup()
    skill = ShellSkill(sandbox=sandbox)

    result = await skill.execute(ShellInput(command=["sh", "-c", "exit 2"]), CTX)

    # Skill succeeds (it ran); the ShellResult inside reports the failure.
    assert result.success
    assert result.data.data.exit_code == 2
    assert not result.data.data.success


@pytest.mark.asyncio
async def test_shell_policy_violation_is_skill_failure(workspace: Path) -> None:
    deny_sandbox = ShellSandbox(config=ShellSandboxConfig(root=workspace, network=NetworkPolicy.DENY))
    await deny_sandbox.setup()
    skill = ShellSkill(sandbox=deny_sandbox)

    result = await skill.execute(ShellInput(command=["curl", "https://evil.example.com"]), CTX)

    assert not result.success
    assert "sandbox policy" in result.error


# ---- test detection --------------------------------------------------------


def test_detect_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect_test_command(tmp_path) == ["uv", "run", "pytest", "-q"]


def test_detect_go_project(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n")
    assert detect_test_command(tmp_path) == ["go", "test", "./..."]


def test_detect_typescript_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}')
    assert detect_test_command(tmp_path) == ["npm", "test"]


def test_detect_makefile_fallback(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("test:\n\ttrue\n")
    assert detect_test_command(tmp_path) == ["make", "test"]


def test_detect_native_runner_wins_over_makefile(tmp_path: Path) -> None:
    # Makefile is a last-resort fallback — a real ecosystem marker takes precedence.
    (tmp_path / "Makefile").write_text("test:\n\ttrue\n")
    (tmp_path / "go.mod").write_text("module x\n")
    assert detect_test_command(tmp_path) == ["go", "test", "./..."]


def test_detect_unknown_returns_none(tmp_path: Path) -> None:
    assert detect_test_command(tmp_path) is None


@pytest.mark.asyncio
async def test_run_tests_auto_detect_unknown_fails(sandbox: ShellSandbox) -> None:
    await sandbox.setup()
    skill = RunTestsSkill(sandbox=sandbox)

    result = await skill.execute(RunTestsInput(), CTX)

    assert not result.success
    assert "could not detect" in result.error


@pytest.mark.asyncio
async def test_run_tests_explicit_command_runs(sandbox: ShellSandbox) -> None:
    await sandbox.setup()
    skill = RunTestsSkill(sandbox=sandbox)

    # explicit command bypasses detection; 'true' exits 0
    result = await skill.execute(RunTestsInput(command=["true"]), CTX)

    assert result.success
    assert result.data.data.success
    assert result.metadata["detected_from"] == "explicit"


@pytest.mark.asyncio
async def test_run_tests_auto_detects_python_marker(sandbox: ShellSandbox, workspace: Path) -> None:
    """Auto-detection picks pytest from pyproject.toml, then runs the detected command.

    NOTE: we override the detected command with a trivial green command to avoid
    nesting `uv run pytest` inside the outer pytest run (which corrupts the event
    loop / nested-uv env). Real-pytest-in-sandbox is exercised by the spec→code
    loop's integration test (Task #29), run outside the unit suite.
    """
    await sandbox.setup()
    (workspace / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\nrequires-python = '>=3.13'\n"
    )

    # detection layer:
    assert detect_test_command(workspace) == ["uv", "run", "pytest", "-q"]

    # execution layer (decoupled from nested-pytest): a green command runs in-sandbox
    skill = RunTestsSkill(sandbox=sandbox)
    result = await skill.execute(RunTestsInput(command=["true"]), CTX)

    assert result.success
    assert result.data.data.success
