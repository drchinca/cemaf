"""Tolerant parser for `openspec validate` diagnostics.

OpenSpec prints human-readable diagnostics to stdout/stderr. We parse known
formats into OpenSpecDiagnostic records and fall through to a raw RAW-wrapped
diagnostic when no pattern matches — never drop information.
"""

from __future__ import annotations

import re

from cemaf.mcp.bridges.openspec.protocols import DiagnosticSeverity, OpenSpecDiagnostic
from cemaf.mcp.bridges.openspec.runtime import strip_ansi

_SEVERITY_PREFIX = re.compile(
    r"^\s*(?P<severity>error|warning|info|warn)\b[:\s-]*(?P<rest>.*)$",
    flags=re.IGNORECASE,
)

_PATH_INLINE = re.compile(
    r"(?P<path>[\w./-]+\.md)(?::(?P<line>\d+))?",
)


def parse_diagnostics(*, stdout: str, stderr: str) -> tuple[OpenSpecDiagnostic, ...]:
    """Parse combined CLI output into structured diagnostics."""
    combined = _clean(stdout) + "\n" + _clean(stderr)
    lines = [line.rstrip() for line in combined.splitlines() if line.strip()]
    parsed: list[OpenSpecDiagnostic] = []
    for line in lines:
        diag = _parse_line(line=line)
        if diag is not None:
            parsed.append(diag)
    return tuple(parsed)


def _clean(text: str) -> str:
    return strip_ansi(text).replace("\r\n", "\n")


def _parse_line(*, line: str) -> OpenSpecDiagnostic | None:
    if not line.strip():
        return None
    match = _SEVERITY_PREFIX.match(line)
    if match is None:
        return OpenSpecDiagnostic(
            severity=DiagnosticSeverity.INFO,
            message=line.strip(),
            raw=line,
        )
    severity = _severity_from_token(token=match.group("severity"))
    rest = match.group("rest").strip()
    path = ""
    path_match = _PATH_INLINE.search(rest)
    if path_match is not None:
        path = path_match.group("path")
    return OpenSpecDiagnostic(
        severity=severity,
        message=rest,
        path=path,
        raw=line,
    )


def _severity_from_token(*, token: str) -> DiagnosticSeverity:
    lower = token.lower()
    if lower == "error":
        return DiagnosticSeverity.ERROR
    if lower in {"warning", "warn"}:
        return DiagnosticSeverity.WARNING
    return DiagnosticSeverity.INFO
