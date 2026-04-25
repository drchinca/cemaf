"""OpenSpec bridge protocols — runtime, result, diagnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from cemaf.core.types import JSON


class DiagnosticSeverity(StrEnum):
    """Severity levels for OpenSpec validation diagnostics."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class SubprocessResult:
    """Result of a subprocess invocation — exit code + captured streams."""

    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def text_stdout(self, *, encoding: str = "utf-8") -> str:
        return self.stdout.decode(encoding=encoding, errors="replace")

    def text_stderr(self, *, encoding: str = "utf-8") -> str:
        return self.stderr.decode(encoding=encoding, errors="replace")


@dataclass(frozen=True, slots=True)
class OpenSpecDiagnostic:
    """A single structured diagnostic from openspec validate."""

    severity: DiagnosticSeverity
    message: str
    path: str = ""
    code: str = ""
    raw: str = ""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Structured outcome of `openspec validate --strict`."""

    change_id: str
    strict: bool
    exit_code: int
    diagnostics: tuple[OpenSpecDiagnostic, ...] = ()
    raw_output: str = ""

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not any(
            d.severity is DiagnosticSeverity.ERROR for d in self.diagnostics
        )

    @property
    def errors(self) -> tuple[OpenSpecDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is DiagnosticSeverity.ERROR)

    @property
    def warnings(self) -> tuple[OpenSpecDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is DiagnosticSeverity.WARNING)

    def to_dict(self) -> JSON:
        return {
            "change_id": self.change_id,
            "strict": self.strict,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "diagnostics": [
                {
                    "severity": d.severity.value,
                    "message": d.message,
                    "path": d.path,
                    "code": d.code,
                }
                for d in self.diagnostics
            ],
        }


@runtime_checkable
class OpenSpecRuntime(Protocol):
    """Abstracts how the OpenSpec CLI is invoked.

    Implementations pick the execution vehicle (system binary, npx-on-demand,
    docker shim) without leaking that choice to callers.
    """

    async def execute(
        self,
        *,
        args: tuple[str, ...],
        cwd: Path,
        timeout: float,
        stdin_data: bytes | None = None,
    ) -> SubprocessResult: ...

    @property
    def display_name(self) -> str: ...


@dataclass(frozen=True, slots=True)
class OpenSpecChange:
    """Materialized OpenSpec change on disk."""

    change_id: str
    root: Path
    files: tuple[str, ...] = field(default_factory=tuple)
