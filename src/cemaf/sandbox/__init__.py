"""
Sandbox module — isolated subprocess execution for dynamically generated code.

Provides resource-adaptive local sandboxing without Docker.
"""

from cemaf.sandbox.capacity import SystemCapacity
from cemaf.sandbox.sandbox import LocalSandbox, SandboxConfig, SandboxResult
from cemaf.sandbox.shell import (
    DEFAULT_NETWORK_ALLOWLIST,
    NetworkPolicy,
    SandboxViolation,
    ShellResult,
    ShellSandbox,
    ShellSandboxConfig,
)

__all__ = [
    "DEFAULT_NETWORK_ALLOWLIST",
    "LocalSandbox",
    "NetworkPolicy",
    "SandboxConfig",
    "SandboxResult",
    "SandboxViolation",
    "ShellResult",
    "ShellSandbox",
    "ShellSandboxConfig",
    "SystemCapacity",
]
