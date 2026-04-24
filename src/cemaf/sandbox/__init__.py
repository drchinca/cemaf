"""
Sandbox module — isolated subprocess execution for dynamically generated code.

Provides resource-adaptive local sandboxing without Docker.
"""

from cemaf.sandbox.capacity import SystemCapacity
from cemaf.sandbox.sandbox import LocalSandbox, SandboxConfig, SandboxResult

__all__ = [
    "LocalSandbox",
    "SandboxConfig",
    "SandboxResult",
    "SystemCapacity",
]
