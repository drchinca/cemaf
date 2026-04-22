"""Tests for the OpenSpec runtime implementations."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cemaf.mcp.bridges.openspec.protocols import OpenSpecRuntime, SubprocessResult
from cemaf.mcp.bridges.openspec.runtime import (
    FakeOpenSpecRuntime,
    NpxOpenSpecRuntime,
    SystemOpenSpecRuntime,
    auto_detect_runtime,
    strip_ansi,
)


def test_strip_ansi_removes_color_codes() -> None:
    colored = "\x1b[31merror\x1b[0m: bad thing"
    assert strip_ansi(colored) == "error: bad thing"


def test_fake_runtime_satisfies_protocol() -> None:
    fake = FakeOpenSpecRuntime()
    assert isinstance(fake, OpenSpecRuntime)


def test_system_runtime_satisfies_protocol() -> None:
    sys_rt = SystemOpenSpecRuntime()
    assert isinstance(sys_rt, OpenSpecRuntime)


def test_npx_runtime_satisfies_protocol() -> None:
    npx_rt = NpxOpenSpecRuntime(version="1.2.3")
    assert isinstance(npx_rt, OpenSpecRuntime)
    assert npx_rt.display_name == "npx:openspec@1.2.3"


@pytest.mark.asyncio
async def test_fake_runtime_returns_default_result_when_no_handler(tmp_path: Path) -> None:
    fake = FakeOpenSpecRuntime()
    result = await fake.execute(args=("list",), cwd=tmp_path, timeout=5.0)
    assert result.ok
    assert result.returncode == 0


@pytest.mark.asyncio
async def test_fake_runtime_dispatches_by_command_prefix(tmp_path: Path) -> None:
    fake = FakeOpenSpecRuntime()
    fake.register_result(
        ("validate",),
        SubprocessResult(returncode=0, stdout=b"ok\n", stderr=b""),
    )
    fake.register_result(
        ("list",),
        SubprocessResult(returncode=0, stdout=b"change-a\nchange-b\n", stderr=b""),
    )
    validate_result = await fake.execute(
        args=("validate", "change-a", "--strict"),
        cwd=tmp_path,
        timeout=5.0,
    )
    list_result = await fake.execute(args=("list",), cwd=tmp_path, timeout=5.0)
    assert validate_result.text_stdout() == "ok\n"
    assert "change-a" in list_result.text_stdout()


@pytest.mark.asyncio
async def test_fake_runtime_records_calls(tmp_path: Path) -> None:
    fake = FakeOpenSpecRuntime()
    await fake.execute(args=("validate", "x"), cwd=tmp_path, timeout=5.0)
    await fake.execute(args=("list",), cwd=tmp_path, timeout=5.0)
    assert len(fake.calls) == 2
    assert fake.calls[0][0] == ("validate", "x")
    assert fake.calls[1][0] == ("list",)


def test_auto_detect_prefers_system_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    # shutil.which substitute — used only to prove the branch choice, not to mock the bridge itself.
    monkeypatch.setattr(
        shutil, "which", lambda binary: "/usr/local/bin/openspec" if binary == "openspec" else None
    )
    runtime = auto_detect_runtime()
    assert isinstance(runtime, SystemOpenSpecRuntime)


def test_auto_detect_falls_back_to_npx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda binary: "/usr/local/bin/npx" if binary == "npx" else None)
    runtime = auto_detect_runtime()
    assert isinstance(runtime, NpxOpenSpecRuntime)


def test_auto_detect_returns_none_when_nothing_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda binary: None)
    assert auto_detect_runtime() is None
