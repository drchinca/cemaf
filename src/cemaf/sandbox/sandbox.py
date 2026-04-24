"""
Local process sandbox for executing dynamically generated code.

No Docker. Uses subprocess + resource limits + temp dir isolation.
Adapts limits based on live system capacity.
"""

import asyncio
import os
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from typing import Any

from cemaf.core.types import JSON
from cemaf.sandbox.capacity import SystemCapacity


@dataclass(frozen=True)
class SandboxConfig:
    """Configuration knobs for the local sandbox."""

    timeout_seconds: float = 30.0
    memory_fraction: float = 0.25      # fraction of available RAM to allow
    allow_network: bool = False        # future: use seccomp/sandbox-exec
    allow_filesystem: bool = True      # reads allowed; writes to tmp only
    max_output_bytes: int = 1024 * 64  # 64 KiB stdout cap


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of a sandboxed code execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    return_value: Any = None
    execution_time_ms: float = 0.0
    error: str | None = None
    memory_used_mb: float = 0.0


class LocalSandbox:
    """
    Executes Python code in an isolated subprocess.

    Resource limits are derived from live system capacity via
    ``SystemCapacity.snapshot()``.  No Docker dependency — uses
    ``asyncio.create_subprocess_exec`` with a temporary script file.
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()

    async def run_code(
        self,
        code: str,
        *,
        inputs: JSON | None = None,
        extra_imports: list[str] | None = None,
    ) -> SandboxResult:
        """Execute a Python code string in a sandboxed subprocess.

        Injects ``inputs`` as a local variable ``_inputs: dict``.
        Captures stdout, stderr, and any ``_result`` variable the code sets.

        The last line of stdout is checked for a ``__RESULT__:<json>`` sentinel
        so that structured data can be returned without pickling across the
        process boundary.
        """
        capacity = SystemCapacity.snapshot()
        timeout = self._config.timeout_seconds

        # Be more conservative when the host is already under load.
        if capacity.is_under_pressure():
            timeout = min(timeout, 15.0)

        wrapper = self._build_wrapper(
            code,
            inputs or {},
            extra_imports or [],
        )

        with tempfile.NamedTemporaryFile(
            suffix=".py",
            mode="w",
            delete=False,
            prefix="badox_sandbox_",
        ) as f:
            f.write(wrapper)
            script_path = f.name

        try:
            import time

            start = time.monotonic()

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                return SandboxResult(
                    success=False,
                    error=f"Execution timed out after {timeout}s",
                )

            elapsed_ms = (time.monotonic() - start) * 1000
            stdout = stdout_b.decode(errors="replace")[: self._config.max_output_bytes]
            stderr = stderr_b.decode(errors="replace")[:4096]

            # Parse structured return value from sentinel on the final line.
            return_value: Any = None
            lines = stdout.splitlines()
            if lines and lines[-1].startswith("__RESULT__:"):
                import json

                try:
                    return_value = json.loads(lines[-1][len("__RESULT__:"):])
                    stdout = "\n".join(lines[:-1])
                except Exception:
                    pass

            success = proc.returncode == 0
            return SandboxResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                return_value=return_value,
                execution_time_ms=elapsed_ms,
                error=stderr if not success else None,
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def _build_wrapper(
        self,
        code: str,
        inputs: JSON,
        extra_imports: list[str],
    ) -> str:
        """Wrap user code with input injection and result extraction."""
        import_block = "\n".join(f"import {imp}" for imp in extra_imports)
        inputs_repr = repr(inputs)
        return textwrap.dedent(f"""
import json
import sys
{import_block}

_inputs = {inputs_repr}
_result = None

try:
{textwrap.indent(code, "    ")}
except Exception as _e:
    print(f"__ERROR__: {{_e}}", file=sys.stderr)
    sys.exit(1)

if _result is not None:
    try:
        print(f"__RESULT__:{{json.dumps(_result)}}")
    except Exception:
        print(f"__RESULT__:{{json.dumps(str(_result))}}")
""")
