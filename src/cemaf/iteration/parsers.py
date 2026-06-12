"""Failure parsers for pytest, ruff, mypy, and a generic shell fallback (SPEC-08)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cemaf.iteration.types import (
    UNKNOWN_SUMMARY_MAX_CHARS,
    FailureItem,
    FailureKind,
    FailureSignal,
)
from cemaf.sandbox.shell import ShellResult

_PYTEST_FAIL_LINE = re.compile(
    r"^FAILED\s+(?P<nodeid>[^\s:]+(?:::\S+)+)\s+-\s+(?P<message>.+)$",
    re.MULTILINE,
)
_PYTEST_LOC = re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+):", re.MULTILINE)

_RUFF_LINE = re.compile(
    r"^(?P<file>[^\s:]+):(?P<line>\d+):\d+:\s+(?P<rule>[A-Z]\d+)\s+(?P<message>.+)$",
    re.MULTILINE,
)

_MYPY_LINE = re.compile(
    r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*(?:\d+:\s*)?error:\s*(?P<message>.+?)(?:\s*\[(?P<rule>[\w\-]+)\])?$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class PytestParser:
    tool: str = "pytest"
    specificity: int = 100
    max_items: int = 20

    def matches(self, result: ShellResult) -> bool:
        if result.success:
            return False
        haystack = result.stdout + result.stderr
        return "pytest" in result.command or "FAILED" in haystack or "test session starts" in haystack

    def parse(self, result: ShellResult) -> FailureSignal | None:
        if result.success:
            return None
        text = result.stdout + "\n" + result.stderr
        items: list[FailureItem] = []
        loc_by_node = {}
        for match in _PYTEST_LOC.finditer(text):
            loc_by_node[match.group("file")] = int(match.group("line"))
        for match in _PYTEST_FAIL_LINE.finditer(text):
            nodeid = match.group("nodeid")
            file_part = nodeid.split("::", 1)[0]
            line = loc_by_node.get(file_part)
            items.append(
                FailureItem(
                    file=file_part,
                    line=line,
                    rule=nodeid,
                    message=match.group("message").strip(),
                )
            )
            if len(items) >= self.max_items:
                break
        truncated = len(items) >= self.max_items and bool(_PYTEST_FAIL_LINE.findall(text)[self.max_items :])
        summary = f"{len(items)} test failure(s)" if items else "pytest failed (no FAILED lines parsed)"
        return FailureSignal(
            kind=FailureKind.TEST_FAILURE,
            summary=summary,
            items=tuple(items),
            raw_command=result.command,
            exit_code=result.exit_code,
            truncated=truncated,
            metadata={"framework": "pytest"},
        )


@dataclass(frozen=True, slots=True)
class RuffParser:
    tool: str = "ruff"
    specificity: int = 90
    max_items: int = 50

    def matches(self, result: ShellResult) -> bool:
        if result.success:
            return False
        return "ruff" in result.command or bool(_RUFF_LINE.search(result.stdout + result.stderr))

    def parse(self, result: ShellResult) -> FailureSignal | None:
        if result.success:
            return None
        text = result.stdout + "\n" + result.stderr
        all_matches = list(_RUFF_LINE.finditer(text))
        items = tuple(
            FailureItem(
                file=m.group("file"),
                line=int(m.group("line")),
                rule=m.group("rule"),
                message=m.group("message").strip(),
            )
            for m in all_matches[: self.max_items]
        )
        return FailureSignal(
            kind=FailureKind.LINT_FAILURE,
            summary=f"{len(all_matches)} ruff violation(s)",
            items=items,
            raw_command=result.command,
            exit_code=result.exit_code,
            truncated=len(all_matches) > self.max_items,
            metadata={"linter": "ruff"},
        )


@dataclass(frozen=True, slots=True)
class MypyParser:
    tool: str = "mypy"
    specificity: int = 90
    max_items: int = 50

    def matches(self, result: ShellResult) -> bool:
        if result.success:
            return False
        return "mypy" in result.command or bool(_MYPY_LINE.search(result.stdout + result.stderr))

    def parse(self, result: ShellResult) -> FailureSignal | None:
        if result.success:
            return None
        text = result.stdout + "\n" + result.stderr
        all_matches = list(_MYPY_LINE.finditer(text))
        items = tuple(
            FailureItem(
                file=m.group("file"),
                line=int(m.group("line")),
                rule=m.group("rule"),
                message=m.group("message").strip(),
            )
            for m in all_matches[: self.max_items]
        )
        return FailureSignal(
            kind=FailureKind.TYPE_FAILURE,
            summary=f"{len(all_matches)} mypy error(s)",
            items=items,
            raw_command=result.command,
            exit_code=result.exit_code,
            truncated=len(all_matches) > self.max_items,
            metadata={"checker": "mypy"},
        )


@dataclass(frozen=True, slots=True)
class ShellFallbackParser:
    """Last-resort parser — captures the failure but does not classify it."""

    tool: str = "shell"
    specificity: int = 0
    max_items: int = 1

    def matches(self, result: ShellResult) -> bool:
        return not result.success

    def parse(self, result: ShellResult) -> FailureSignal | None:
        if result.success:
            return None
        raw = (result.stderr or result.stdout or "").strip()
        summary = raw[:UNKNOWN_SUMMARY_MAX_CHARS] if raw else f"command exited {result.exit_code}"
        return FailureSignal(
            kind=FailureKind.UNKNOWN,
            summary=summary,
            items=(),
            raw_command=result.command,
            exit_code=result.exit_code,
            truncated=len(raw) > UNKNOWN_SUMMARY_MAX_CHARS,
            metadata={"timed_out": str(result.timed_out).lower()},
        )
