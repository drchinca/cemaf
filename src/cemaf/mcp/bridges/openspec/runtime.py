"""OpenSpec runtime implementations — System, Npx, Fake."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cemaf.mcp.bridges.openspec.protocols import SubprocessResult

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI color codes from text."""
    return _ANSI_ESCAPE.sub("", text)


async def _run_subprocess(
    *,
    cmd: tuple[str, ...],
    cwd: Path,
    timeout: float,
    stdin_data: bytes | None,
) -> SubprocessResult:
    """Run a subprocess with timeout + process-group kill on cancellation."""
    stdin_pipe = asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdin=stdin_pipe,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await proc.communicate(input=stdin_data)
    except (TimeoutError, asyncio.CancelledError):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            async with asyncio.timeout(2.0):
                await proc.wait()
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
        raise
    return SubprocessResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
    )


class SystemOpenSpecRuntime:
    """Invoke the `openspec` binary already on PATH."""

    def __init__(self, *, binary: str = "openspec") -> None:
        self._binary = binary

    @property
    def display_name(self) -> str:
        return f"system:{self._binary}"

    async def execute(
        self,
        *,
        args: tuple[str, ...],
        cwd: Path,
        timeout: float,
        stdin_data: bytes | None = None,
    ) -> SubprocessResult:
        return await _run_subprocess(
            cmd=(self._binary, *args),
            cwd=cwd,
            timeout=timeout,
            stdin_data=stdin_data,
        )


class NpxOpenSpecRuntime:
    """Invoke OpenSpec via `npx -y openspec@<version>`.

    Used when the user has node but not a global openspec install.
    """

    def __init__(self, *, version: str = "latest", npx: str = "npx") -> None:
        self._version = version
        self._npx = npx

    @property
    def display_name(self) -> str:
        return f"npx:openspec@{self._version}"

    async def execute(
        self,
        *,
        args: tuple[str, ...],
        cwd: Path,
        timeout: float,
        stdin_data: bytes | None = None,
    ) -> SubprocessResult:
        package = f"openspec@{self._version}" if self._version else "openspec"
        return await _run_subprocess(
            cmd=(self._npx, "-y", package, *args),
            cwd=cwd,
            timeout=timeout,
            stdin_data=stdin_data,
        )


FakeHandler = Callable[[tuple[str, ...], Path, bytes | None], SubprocessResult]


@dataclass
class FakeOpenSpecRuntime:
    """In-memory fake — dispatch by command prefix, record calls.

    Designed for tests. Zero subprocess calls. Preserves the OpenSpecRuntime
    protocol shape so code under test never knows it's not real.
    """

    handlers: dict[tuple[str, ...], FakeHandler] = field(default_factory=dict)
    default_result: SubprocessResult = field(
        default_factory=lambda: SubprocessResult(returncode=0, stdout=b"", stderr=b"")
    )
    calls: list[tuple[tuple[str, ...], Path, bytes | None]] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return "fake:openspec"

    def register(self, prefix: tuple[str, ...], handler: FakeHandler) -> None:
        self.handlers[prefix] = handler

    def register_result(self, prefix: tuple[str, ...], result: SubprocessResult) -> None:
        self.handlers[prefix] = lambda _args, _cwd, _stdin: result

    async def execute(
        self,
        *,
        args: tuple[str, ...],
        cwd: Path,
        timeout: float,
        stdin_data: bytes | None = None,
    ) -> SubprocessResult:
        self.calls.append((args, cwd, stdin_data))
        for prefix, handler in self.handlers.items():
            if args[: len(prefix)] == prefix:
                return handler(args, cwd, stdin_data)
        return self.default_result


def auto_detect_runtime(
    *,
    version: str = "latest",
    binary: str = "openspec",
    npx: str = "npx",
) -> SystemOpenSpecRuntime | NpxOpenSpecRuntime | None:
    """Pick SystemOpenSpecRuntime if binary on PATH, else NpxOpenSpecRuntime if npx on PATH, else None."""
    if shutil.which(binary) is not None:
        return SystemOpenSpecRuntime(binary=binary)
    if shutil.which(npx) is not None:
        return NpxOpenSpecRuntime(version=version, npx=npx)
    return None


__all__ = [
    "SystemOpenSpecRuntime",
    "NpxOpenSpecRuntime",
    "FakeOpenSpecRuntime",
    "FakeHandler",
    "auto_detect_runtime",
    "strip_ansi",
]


# Re-export Any for typing consumers that want FakeHandler compositions
_ = Any
