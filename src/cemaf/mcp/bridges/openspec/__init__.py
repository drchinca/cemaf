"""OpenSpec MCP bridge — lets CEMAF meta-agents read/write/validate OpenSpec change proposals."""

from cemaf.mcp.bridges.openspec.protocols import (
    DiagnosticSeverity,
    OpenSpecChange,
    OpenSpecDiagnostic,
    OpenSpecRuntime,
    SubprocessResult,
    ValidationReport,
)
from cemaf.mcp.bridges.openspec.runtime import (
    FakeOpenSpecRuntime,
    NpxOpenSpecRuntime,
    SystemOpenSpecRuntime,
    auto_detect_runtime,
)
from cemaf.mcp.bridges.openspec.tools import (
    OpenSpecDeleteChangeTool,
    OpenSpecListTool,
    OpenSpecShowTool,
    OpenSpecValidateTool,
    OpenSpecWriteChangeTool,
    create_openspec_tools,
)
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace

__all__ = [
    "DiagnosticSeverity",
    "FakeOpenSpecRuntime",
    "NpxOpenSpecRuntime",
    "OpenSpecChange",
    "OpenSpecDeleteChangeTool",
    "OpenSpecDiagnostic",
    "OpenSpecListTool",
    "OpenSpecRuntime",
    "OpenSpecShowTool",
    "OpenSpecValidateTool",
    "OpenSpecWorkspace",
    "OpenSpecWriteChangeTool",
    "SubprocessResult",
    "SystemOpenSpecRuntime",
    "ValidationReport",
    "auto_detect_runtime",
    "create_openspec_tools",
]
