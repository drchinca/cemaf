"""OpenSpec tools exposed to CEMAF agents — list, show, validate, write, delete."""

from __future__ import annotations

from typing import Any

from cemaf.core.result import Result
from cemaf.core.types import JSON, ToolID
from cemaf.mcp.bridges.openspec.parser import parse_diagnostics
from cemaf.mcp.bridges.openspec.protocols import (
    OpenSpecRuntime,
    ValidationReport,
)
from cemaf.mcp.bridges.openspec.workspace import OpenSpecWorkspace
from cemaf.tools.base import Tool, ToolResult, ToolSchema

DEFAULT_TIMEOUT = 30.0


class OpenSpecValidateTool(Tool):
    """Run `openspec validate <change_id> [--strict]`; return structured report."""

    def __init__(
        self,
        *,
        runtime: OpenSpecRuntime,
        workspace: OpenSpecWorkspace,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._runtime = runtime
        self._workspace = workspace
        self._timeout = timeout

    @property
    def id(self) -> ToolID:
        return ToolID("openspec_validate")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="openspec_validate",
            description="Validate an OpenSpec change proposal. Returns structured diagnostics.",
            parameters={
                "type": "object",
                "properties": {
                    "change_id": {
                        "type": "string",
                        "description": "Identifier of the change under openspec/changes/.",
                    },
                    "strict": {
                        "type": "boolean",
                        "description": "Run validation in strict mode.",
                        "default": True,
                    },
                },
            },
            required=("change_id",),
            is_read_only=True,
            is_concurrent_safe=True,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        change_id = kwargs.get("change_id", "")
        strict = bool(kwargs.get("strict", True))
        if not change_id:
            return Result.fail(error="change_id is required")

        args: tuple[str, ...] = ("validate", change_id)
        if strict:
            args = (*args, "--strict")

        sub = await self._runtime.execute(
            args=args,
            cwd=self._workspace.root,
            timeout=self._timeout,
        )
        diagnostics = parse_diagnostics(stdout=sub.text_stdout(), stderr=sub.text_stderr())
        report = ValidationReport(
            change_id=change_id,
            strict=strict,
            exit_code=sub.returncode,
            diagnostics=diagnostics,
            raw_output=sub.text_stdout() + sub.text_stderr(),
        )
        if report.passed:
            return Result.ok(data=report.to_dict(), metadata={"runtime": self._runtime.display_name})
        return Result.fail(
            error=f"openspec validate failed (exit={sub.returncode})",
            metadata={"report": report.to_dict(), "runtime": self._runtime.display_name},
        )


class OpenSpecListTool(Tool):
    """List all changes in the workspace."""

    def __init__(self, *, workspace: OpenSpecWorkspace) -> None:
        self._workspace = workspace

    @property
    def id(self) -> ToolID:
        return ToolID("openspec_list")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="openspec_list",
            description="List OpenSpec change proposals in the workspace.",
            parameters={"type": "object", "properties": {}},
            required=(),
            is_read_only=True,
            is_concurrent_safe=True,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        changes = await self._workspace.list_changes()
        return Result.ok(data={"changes": list(changes)})


class OpenSpecShowTool(Tool):
    """Show a change's files and contents."""

    def __init__(self, *, workspace: OpenSpecWorkspace) -> None:
        self._workspace = workspace

    @property
    def id(self) -> ToolID:
        return ToolID("openspec_show")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="openspec_show",
            description="Read a change's files and return their contents.",
            parameters={
                "type": "object",
                "properties": {
                    "change_id": {"type": "string", "description": "Change identifier."},
                },
            },
            required=("change_id",),
            is_read_only=True,
            is_concurrent_safe=True,
        )

    @property
    def is_read_only(self) -> bool:
        return True

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        change_id = kwargs.get("change_id", "")
        if not change_id:
            return Result.fail(error="change_id is required")
        change = await self._workspace.read_change(change_id=change_id)
        if change is None:
            return Result.fail(error=f"change not found: {change_id}")
        contents: JSON = {}
        for rel in change.files:
            contents[rel] = (change.root / rel).read_text(encoding="utf-8")
        return Result.ok(
            data={"change_id": change.change_id, "files": contents},
        )


class OpenSpecWriteChangeTool(Tool):
    """Write (or overwrite) a change's files atomically."""

    def __init__(self, *, workspace: OpenSpecWorkspace) -> None:
        self._workspace = workspace

    @property
    def id(self) -> ToolID:
        return ToolID("openspec_write_change")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="openspec_write_change",
            description="Write or overwrite an OpenSpec change's files atomically.",
            parameters={
                "type": "object",
                "properties": {
                    "change_id": {"type": "string", "description": "Change identifier."},
                    "files": {
                        "type": "object",
                        "description": "Map of relative path -> file contents.",
                        "additionalProperties": {"type": "string"},
                    },
                },
            },
            required=("change_id", "files"),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        change_id = kwargs.get("change_id", "")
        files = kwargs.get("files", {})
        if not change_id:
            return Result.fail(error="change_id is required")
        if not isinstance(files, dict) or not files:
            return Result.fail(error="files must be a non-empty object")
        try:
            change = await self._workspace.write_change(change_id=change_id, files=files)
        except ValueError as exc:
            return Result.fail(error=str(exc))
        return Result.ok(
            data={
                "change_id": change.change_id,
                "root": str(change.root),
                "files": list(change.files),
            },
        )


class OpenSpecDeleteChangeTool(Tool):
    """Delete a change directory."""

    def __init__(self, *, workspace: OpenSpecWorkspace) -> None:
        self._workspace = workspace

    @property
    def id(self) -> ToolID:
        return ToolID("openspec_delete_change")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="openspec_delete_change",
            description="Delete an OpenSpec change directory.",
            parameters={
                "type": "object",
                "properties": {
                    "change_id": {"type": "string"},
                },
            },
            required=("change_id",),
            is_destructive=True,
        )

    @property
    def is_destructive(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        change_id = kwargs.get("change_id", "")
        if not change_id:
            return Result.fail(error="change_id is required")
        try:
            deleted = await self._workspace.delete_change(change_id=change_id)
        except ValueError as exc:
            return Result.fail(error=str(exc))
        return Result.ok(data={"change_id": change_id, "deleted": deleted})


def create_openspec_tools(
    *,
    runtime: OpenSpecRuntime,
    workspace: OpenSpecWorkspace,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Tool, ...]:
    """Return the five OpenSpec tools bound to a runtime + workspace."""
    return (
        OpenSpecValidateTool(runtime=runtime, workspace=workspace, timeout=timeout),
        OpenSpecListTool(workspace=workspace),
        OpenSpecShowTool(workspace=workspace),
        OpenSpecWriteChangeTool(workspace=workspace),
        OpenSpecDeleteChangeTool(workspace=workspace),
    )
