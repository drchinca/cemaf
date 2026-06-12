"""File-operation skills — path-confined to a workspace root.

Every path is resolved against the workspace root and rejected if it escapes
(no ``../../etc/passwd``). Skills return the CEMAF ``SkillResult`` contract and
never raise across the boundary — failures come back as ``Result.fail``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from cemaf.core.result import Result
from cemaf.core.types import SkillID
from cemaf.skills.base import Skill, SkillContext, SkillOutput, SkillResult
from cemaf.tools.base import Tool


class PathEscapeError(ValueError):
    """Raised when a target path would escape the workspace root."""


def _resolve_within(root: Path, relpath: str) -> Path:
    """Resolve relpath under root, refusing anything that escapes it."""
    target = (root / relpath).resolve()
    if not target.is_relative_to(root.resolve()):
        raise PathEscapeError(f"path escapes workspace: {relpath!r}")
    return target


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


class WriteFileInput(BaseModel):
    path: str
    content: str


class WriteFileSkill(Skill[WriteFileInput, str]):
    """Create or overwrite a file in the workspace (parent dirs auto-created)."""

    def __init__(self, *, workspace: Path) -> None:
        self._root = workspace

    @property
    def id(self) -> SkillID:
        return SkillID("write_file")

    @property
    def description(self) -> str:
        return "Create or overwrite a file at a workspace-relative path."

    @property
    def tools(self) -> tuple[Tool, ...]:
        return ()

    async def execute(self, input: WriteFileInput, context: SkillContext) -> SkillResult:
        try:
            target = _resolve_within(self._root, input.path)
        except PathEscapeError as exc:
            return Result.fail(str(exc))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(input.content)
        return Result.ok(SkillOutput(data=input.path), metadata={"bytes": len(input.content)})


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class ReadFileInput(BaseModel):
    path: str


class ReadFileSkill(Skill[ReadFileInput, str]):
    """Read a file from the workspace."""

    def __init__(self, *, workspace: Path) -> None:
        self._root = workspace

    @property
    def id(self) -> SkillID:
        return SkillID("read_file")

    @property
    def description(self) -> str:
        return "Read the contents of a workspace-relative file."

    @property
    def tools(self) -> tuple[Tool, ...]:
        return ()

    async def execute(self, input: ReadFileInput, context: SkillContext) -> SkillResult:
        try:
            target = _resolve_within(self._root, input.path)
        except PathEscapeError as exc:
            return Result.fail(str(exc))
        if not target.is_file():
            return Result.fail(f"file not found: {input.path}")
        return Result.ok(SkillOutput(data=target.read_text()))


# ---------------------------------------------------------------------------
# Edit (exact-string replace)
# ---------------------------------------------------------------------------


class EditFileInput(BaseModel):
    path: str
    old: str
    new: str
    expect_count: int | None = None  # if set, require exactly this many replacements


class EditFileSkill(Skill[EditFileInput, str]):
    """Replace exact-string occurrences in a workspace file (no regex)."""

    def __init__(self, *, workspace: Path) -> None:
        self._root = workspace

    @property
    def id(self) -> SkillID:
        return SkillID("edit_file")

    @property
    def description(self) -> str:
        return "Replace an exact substring in a workspace file."

    @property
    def tools(self) -> tuple[Tool, ...]:
        return ()

    async def execute(self, input: EditFileInput, context: SkillContext) -> SkillResult:
        try:
            target = _resolve_within(self._root, input.path)
        except PathEscapeError as exc:
            return Result.fail(str(exc))
        if not target.is_file():
            return Result.fail(f"file not found: {input.path}")
        original = target.read_text()
        count = original.count(input.old)
        if count == 0:
            return Result.fail(f"old string not found in {input.path}")
        if input.expect_count is not None and count != input.expect_count:
            return Result.fail(f"expected {input.expect_count} occurrences in {input.path}, found {count}")
        target.write_text(original.replace(input.old, input.new))
        return Result.ok(SkillOutput(data=input.path), metadata={"replacements": count})


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class ListDirInput(BaseModel):
    path: str = "."
    max_entries: int = 500


class ListDirSkill(Skill[ListDirInput, tuple[str, ...]]):
    """List files in the workspace (recursive, relative paths)."""

    def __init__(self, *, workspace: Path) -> None:
        self._root = workspace

    @property
    def id(self) -> SkillID:
        return SkillID("list_dir")

    @property
    def description(self) -> str:
        return "List files under a workspace-relative directory (recursive)."

    @property
    def tools(self) -> tuple[Tool, ...]:
        return ()

    async def execute(self, input: ListDirInput, context: SkillContext) -> SkillResult:
        try:
            base = _resolve_within(self._root, input.path)
        except PathEscapeError as exc:
            return Result.fail(str(exc))
        if not base.is_dir():
            return Result.fail(f"directory not found: {input.path}")
        root = self._root.resolve()
        files = sorted(
            str(p.relative_to(root))
            for p in base.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts
        )
        return Result.ok(SkillOutput(data=tuple(files[: input.max_entries])))
