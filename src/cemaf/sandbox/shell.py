"""Polyglot shell sandbox — run arbitrary commands in an isolated working dir.

Language-agnostic by construction: where ``LocalSandbox`` executes Python code
strings, ``ShellSandbox`` executes any command (``uv``, ``pytest``, ``npm``,
``go test``, ``gradle``, ``cargo``, ``git``...) inside a designated working
directory. This is the substrate the agent skill kit (ShellSkill, RunTestsSkill)
builds on so a single agent loop can produce Python, TypeScript, Go, Kotlin, etc.

Safety model (no Docker; best-effort on a shared host):
- cwd confinement: commands run with ``cwd`` set to the sandbox root; the runner
  refuses a cwd that escapes the configured root.
- timeout: every command is wall-clock bounded; on timeout the process tree is
  killed.
- output caps: stdout/stderr truncated to a byte budget (the tail of a 200 MB
  build log never reaches the LLM).
- network policy: ``deny`` by default. Two complementary screens run before a
  command executes: (1) network-capable binaries (``curl``, ``wget``, ``nc``,
  ``ssh``, ``scp``, ``rsync``...) are refused — under ``deny`` outright, under
  ``allowlist`` unless the command carries an ``http(s)://`` URL whose host is
  allow-listed; (2) any ``http(s)://`` token in argv is screened host-by-host.
  Shell ``-c <script>`` payloads are unwrapped so ``sh -c 'curl evil'`` is caught.
  (Full network isolation needs OS sandboxing; this is a strong guardrail, not a
  jail — documented as such.)
- env scrubbing: by default the child gets a minimal env, NOT the parent's.
  Secret-shaped keys (``*_KEY``, ``*_TOKEN``, ``*_SECRET``, ``AWS_*``...) are
  dropped even when a caller passes them explicitly, unless their exact name is
  listed in ``ShellSandboxConfig.allow_env_keys``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

_log = logging.getLogger(__name__)

# Package registries an agent legitimately needs to install dependencies.
DEFAULT_NETWORK_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
        "proxy.golang.org",
        "sum.golang.org",
        "repo.maven.apache.org",
        "dl.google.com",
        "crates.io",
        "static.crates.io",
        "index.crates.io",
        "github.com",
        "codeload.github.com",
        "objects.githubusercontent.com",
    }
)

# Executables that reach the network without ever spelling out an http(s):// URL.
# Under DENY these are refused outright — the URL-substring screen alone misses
# `curl example.com`, `nc host 443`, `ssh host`, scheme-less `wget host/p`, etc.
_NETWORK_BINARIES: Final[frozenset[str]] = frozenset(
    {
        "curl",
        "wget",
        "nc",
        "ncat",
        "netcat",
        "socat",
        "telnet",
        "ssh",
        "scp",
        "sftp",
        "ftp",
        "rsync",
    }
)

# Shell interpreters whose `-c <script>` payload smuggles arbitrary commands past
# argv[0] screening. Under DENY we scan their inline script for network binaries.
_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"sh", "bash", "zsh", "dash", "ksh"})

# Substrings that mark an env var as secret-shaped. Such keys are dropped from the
# child env even when a caller passes them explicitly — env scrubbing exists to keep
# inherited cloud creds out of agent-run subprocesses; an explicit pass must not
# silently re-introduce them. Pass-through of a genuinely-needed secret is opt-in via
# ShellSandboxConfig.allow_env_keys.
_SECRET_ENV_MARKERS: Final[tuple[str, ...]] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE",
    "SESSION",
)
_SECRET_ENV_PREFIXES: Final[tuple[str, ...]] = ("AWS_", "GCP_", "GOOGLE_", "AZURE_", "OPENAI_", "ANTHROPIC_")

# Env vars safe to pass through to the child by default (PATH etc.).
_DEFAULT_PASSTHROUGH_ENV: Final[tuple[str, ...]] = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")

_MAX_OUTPUT_BYTES: Final[int] = 64 * 1024
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0


class NetworkPolicy(StrEnum):
    DENY = "deny"  # block commands referencing non-allowlisted http(s) URLs
    ALLOWLIST = "allowlist"  # allow http(s) URLs whose host is on the allowlist
    ALLOW = "allow"  # no screening (use only in trusted contexts)


class SandboxViolation(Exception):
    """Raised when a command violates the sandbox policy (escape, blocked host)."""


@dataclass(frozen=True)
class ShellSandboxConfig:
    """Configuration for a shell sandbox bound to one working directory."""

    root: Path
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_output_bytes: int = _MAX_OUTPUT_BYTES
    network: NetworkPolicy = NetworkPolicy.DENY
    network_allowlist: frozenset[str] = DEFAULT_NETWORK_ALLOWLIST
    passthrough_env: tuple[str, ...] = _DEFAULT_PASSTHROUGH_ENV
    extra_env: Mapping[str, str] = field(default_factory=dict)
    # Secret-shaped env keys (see _SECRET_ENV_MARKERS) are scrubbed from the child
    # env unless their exact name is listed here — opt-in escape hatch for a creds
    # var a tool genuinely needs.
    allow_env_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ShellResult:
    """Outcome of a shell command execution."""

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    timed_out: bool = False
    truncated: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class ShellSandbox:
    """Runs shell commands in an isolated working directory with policy guards."""

    def __init__(self, *, config: ShellSandboxConfig) -> None:
        self._config = config
        self._root = config.root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    async def setup(self) -> None:
        """Create the sandbox root if it does not exist."""
        self._root.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        command: str | Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout_seconds: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShellResult:
        """Execute a command inside the sandbox. argv list preferred over string."""
        argv = shlex.split(command) if isinstance(command, str) else list(command)
        if not argv:
            raise SandboxViolation("empty command")

        display = command if isinstance(command, str) else shlex.join(argv)
        self._screen_network(argv=argv, display=display)
        run_cwd = self._resolve_cwd(cwd=cwd)
        timeout = timeout_seconds if timeout_seconds is not None else self._config.timeout_seconds
        child_env = self._build_env(extra=env)

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(run_cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=child_env,
                start_new_session=True,  # own process group → kill the whole tree on timeout
            )
        except FileNotFoundError as exc:
            return ShellResult(
                command=display,
                exit_code=127,
                stderr=f"command not found: {argv[0]} ({exc})",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            self._kill_tree(proc=proc)
            await proc.communicate()
            stdout_b, stderr_b = b"", f"timed out after {timeout}s".encode()

        duration_ms = (time.monotonic() - start) * 1000
        stdout, st_trunc = self._cap(stdout_b)
        stderr, se_trunc = self._cap(stderr_b)
        return ShellResult(
            command=display,
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            truncated=st_trunc or se_trunc,
        )

    def _resolve_cwd(self, *, cwd: str | Path | None) -> Path:
        if cwd is None:
            return self._root
        candidate = (self._root / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).resolve()
        if not candidate.is_relative_to(self._root):
            raise SandboxViolation(f"cwd escapes sandbox root: {cwd!r}")
        return candidate

    def _build_env(self, *, extra: Mapping[str, str] | None) -> dict[str, str]:
        env: dict[str, str] = {k: os.environ[k] for k in self._config.passthrough_env if k in os.environ}
        env.update(self._config.extra_env)
        if extra:
            env.update(extra)
        return self._scrub_secrets(env=env)

    def _scrub_secrets(self, *, env: dict[str, str]) -> dict[str, str]:
        """Drop secret-shaped keys unless explicitly allow-listed; log what was scrubbed."""
        allow = self._config.allow_env_keys
        kept: dict[str, str] = {}
        scrubbed: list[str] = []
        for key, value in env.items():
            if key in allow or not self._is_secret_key(key=key):
                kept[key] = value
            else:
                scrubbed.append(key)
        if scrubbed:
            _log.warning("sandbox env scrubbed %d secret-shaped key(s): %s", len(scrubbed), sorted(scrubbed))
        return kept

    @staticmethod
    def _is_secret_key(*, key: str) -> bool:
        upper = key.upper()
        if any(upper.startswith(prefix) for prefix in _SECRET_ENV_PREFIXES):
            return True
        return any(marker in upper for marker in _SECRET_ENV_MARKERS)

    def _screen_network(self, *, argv: Sequence[str], display: str) -> None:
        if self._config.network == NetworkPolicy.ALLOW:
            return
        self._screen_network_binaries(argv=argv, display=display)
        for token in argv:
            for scheme in ("http://", "https://"):
                idx = token.find(scheme)
                if idx == -1:
                    continue
                rest = token[idx + len(scheme) :]
                host = rest.split("/", 1)[0].split("@")[-1].split(":")[0].lower()
                if self._config.network == NetworkPolicy.DENY:
                    raise SandboxViolation(
                        f"network DENY: command references URL host {host!r} in {display!r}"
                    )
                if host not in self._config.network_allowlist:
                    raise SandboxViolation(f"network ALLOWLIST: host {host!r} not allowed (in {display!r})")

    def _screen_network_binaries(self, *, argv: Sequence[str], display: str) -> None:
        """Refuse network-capable executables that bypass URL screening (curl host, nc, ssh...).

        Scheme-less invocations (`curl example.com`) carry no http(s):// token, so the
        URL screen alone is blind to them. Policy by mode:
        - DENY: refuse any network binary outright.
        - ALLOWLIST: permit only when the command carries an http(s):// URL (the URL screen
          then validates that host against the allowlist). A network binary with no URL
          token (`nc host 443`, `curl example.com`, `ssh host`) is unverifiable → refused.

        Shell `-c <script>` payloads are unwrapped so `sh -c 'curl evil'` is caught too.
        """
        for command in self._expand_shell_payloads(argv=argv):
            has_url = any(("http://" in t or "https://" in t) for t in command)
            for token in command:
                name = self._executable_name(token=token)
                if name not in _NETWORK_BINARIES:
                    continue
                if self._config.network == NetworkPolicy.ALLOWLIST and has_url:
                    # URL screen will validate the host against the allowlist.
                    continue
                raise SandboxViolation(
                    f"network {self._config.network.value.upper()}: "
                    f"network binary {name!r} refused in {display!r} "
                    "(no host allowlisting for raw sockets / scheme-less transfers)"
                )

    @staticmethod
    def _expand_shell_payloads(*, argv: Sequence[str]) -> list[Sequence[str]]:
        """Yield the argv plus any `sh -c <script>` inner command split out for screening."""
        commands: list[Sequence[str]] = [argv]
        if not argv:
            return commands
        if ShellSandbox._executable_name(token=argv[0]) in _SHELL_INTERPRETERS:
            for idx, token in enumerate(argv):
                if token == "-c" and idx + 1 < len(argv):
                    try:
                        commands.append(shlex.split(argv[idx + 1]))
                    except ValueError:
                        # Unparseable script — fall back to scanning the raw payload tokens.
                        commands.append([argv[idx + 1]])
        return commands

    @staticmethod
    def _executable_name(*, token: str) -> str:
        """Reduce an argv token to its bare executable name (strip path + drop env-var prefixes)."""
        # `/usr/bin/curl` → `curl`; an env-assignment prefix like `FOO=bar` is not an executable.
        if "=" in token and not token.startswith("/") and "/" not in token.split("=", 1)[0]:
            return ""
        return Path(token).name.lower()

    def _cap(self, raw: bytes) -> tuple[str, bool]:
        limit = self._config.max_output_bytes
        if len(raw) <= limit:
            return raw.decode(errors="replace"), False
        # keep the TAIL — failures + tracebacks live at the end of build/test logs
        tail = raw[-limit:].decode(errors="replace")
        return f"...[truncated {len(raw) - limit} bytes]...\n{tail}", True

    @staticmethod
    def _kill_tree(*, proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
