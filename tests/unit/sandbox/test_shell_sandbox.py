"""Contract tests for cemaf.sandbox.ShellSandbox — the polyglot execution substrate.

Uses real subprocesses (echo, sh, python3, sleep) and real tmp dirs — no mocks.
Proves the sandbox runs arbitrary commands (language-agnostic), confines cwd,
bounds time + output, scrubs env, and screens network per policy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cemaf.sandbox import (
    NetworkPolicy,
    SandboxViolation,
    ShellSandbox,
    ShellSandboxConfig,
)


def _sandbox(tmp_path: Path, **kw) -> ShellSandbox:
    return ShellSandbox(config=ShellSandboxConfig(root=tmp_path, **kw))


@pytest.mark.asyncio
async def test_runs_a_basic_command(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    result = await sb.run(["echo", "hello"])

    assert result.success
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


@pytest.mark.asyncio
async def test_runs_command_from_string(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    result = await sb.run("echo polyglot")

    assert result.success
    assert "polyglot" in result.stdout


@pytest.mark.asyncio
async def test_nonzero_exit_is_not_success(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    result = await sb.run(["sh", "-c", "exit 3"])

    assert not result.success
    assert result.exit_code == 3


@pytest.mark.asyncio
async def test_command_runs_in_sandbox_root(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    result = await sb.run(["pwd"])

    assert result.success
    # macOS /var → /private/var symlink: compare resolved paths
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


@pytest.mark.asyncio
async def test_polyglot_runs_python_then_writes_file(tmp_path: Path) -> None:
    """The whole point: drive any toolchain. Here: python writes a file, sh reads it."""
    sb = _sandbox(tmp_path)
    await sb.setup()

    write = await sb.run([sys.executable, "-c", "open('out.txt','w').write('ok')"])
    assert write.success
    read = await sb.run(["cat", "out.txt"])

    assert read.success
    assert read.stdout.strip() == "ok"
    assert (tmp_path / "out.txt").read_text() == "ok"


@pytest.mark.asyncio
async def test_cwd_subdir_is_allowed(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()
    (tmp_path / "sub").mkdir()

    result = await sb.run(["pwd"], cwd="sub")

    assert result.success
    assert Path(result.stdout.strip()).resolve() == (tmp_path / "sub").resolve()


@pytest.mark.asyncio
async def test_cwd_escape_is_rejected(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    with pytest.raises(SandboxViolation, match="escapes sandbox"):
        await sb.run(["pwd"], cwd="../../etc")


@pytest.mark.asyncio
async def test_timeout_kills_long_command(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path, timeout_seconds=0.5)
    await sb.setup()

    result = await sb.run(["sleep", "5"])

    assert result.timed_out
    assert not result.success


@pytest.mark.asyncio
async def test_output_is_capped_with_tail(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path, max_output_bytes=100)
    await sb.setup()

    # emit ~1KB; expect truncation keeping the tail
    result = await sb.run([sys.executable, "-c", "print('x' * 1000)"])

    assert result.truncated
    assert len(result.stdout) < 300
    assert "truncated" in result.stdout


@pytest.mark.asyncio
async def test_env_is_scrubbed_by_default(tmp_path: Path, monkeypatch) -> None:
    # A secret in the parent env must NOT reach the child by default.
    monkeypatch.setenv("SECRET_TOKEN", "leaked")
    sb = _sandbox(tmp_path)
    await sb.setup()

    code = "import os; print(os.environ.get('SECRET_TOKEN', 'ABSENT'))"
    result = await sb.run([sys.executable, "-c", code])

    assert result.stdout.strip() == "ABSENT"


@pytest.mark.asyncio
async def test_extra_env_is_passed(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    result = await sb.run(
        [sys.executable, "-c", "import os; print(os.environ['MY_VAR'])"],
        env={"MY_VAR": "present"},
    )

    assert result.stdout.strip() == "present"


@pytest.mark.asyncio
async def test_network_deny_blocks_url_command(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path, network=NetworkPolicy.DENY)
    await sb.setup()

    with pytest.raises(SandboxViolation, match="network DENY"):
        await sb.run(["curl", "https://evil.example.com/x"])


@pytest.mark.asyncio
async def test_network_allowlist_permits_pypi_blocks_others(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path, network=NetworkPolicy.ALLOWLIST)
    await sb.setup()

    # allowlisted host: screening passes (command may still fail to run — fine, we only test the guard)
    with pytest.raises(SandboxViolation, match="not allowed"):
        await sb.run(["curl", "https://evil.example.com/x"])

    # pypi.org is on the default allowlist → screening must NOT raise.
    # use 'true' so we don't actually hit the network; the URL is just an argv token.
    ok = await sb.run(["true", "https://pypi.org/simple/"])
    assert ok.success


@pytest.mark.asyncio
async def test_network_allow_skips_screening(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path, network=NetworkPolicy.ALLOW)
    await sb.setup()

    # No SandboxViolation even with an arbitrary URL; 'true' ignores its args.
    result = await sb.run(["true", "https://anything.example.com"])
    assert result.success


@pytest.mark.asyncio
async def test_missing_command_returns_127(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    result = await sb.run(["this-binary-does-not-exist-xyz"])

    assert result.exit_code == 127
    assert not result.success
    assert "not found" in result.stderr


@pytest.mark.asyncio
async def test_empty_command_raises(tmp_path: Path) -> None:
    sb = _sandbox(tmp_path)
    await sb.setup()

    with pytest.raises(SandboxViolation, match="empty command"):
        await sb.run([])
