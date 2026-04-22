"""Tests for the OpenSpec diagnostic parser."""

from __future__ import annotations

from cemaf.mcp.bridges.openspec.parser import parse_diagnostics
from cemaf.mcp.bridges.openspec.protocols import DiagnosticSeverity


def test_parses_error_lines() -> None:
    output = "error: scenario missing for Requirement X in specs/x/spec.md\n"
    diags = parse_diagnostics(stdout=output, stderr="")
    assert len(diags) == 1
    assert diags[0].severity is DiagnosticSeverity.ERROR
    assert "scenario missing" in diags[0].message
    assert diags[0].path == "specs/x/spec.md"


def test_parses_warning_and_info_lines() -> None:
    output = "warning: deprecated header format in proposal.md\ninfo: validating 3 deltas\n"
    diags = parse_diagnostics(stdout=output, stderr="")
    severities = [d.severity for d in diags]
    assert DiagnosticSeverity.WARNING in severities
    assert DiagnosticSeverity.INFO in severities


def test_strips_ansi_colors_before_parsing() -> None:
    colored = "\x1b[31merror\x1b[0m: boom\n"
    diags = parse_diagnostics(stdout=colored, stderr="")
    assert len(diags) == 1
    assert diags[0].severity is DiagnosticSeverity.ERROR
    assert diags[0].message == "boom"


def test_unknown_lines_fall_through_as_info() -> None:
    output = "random unstructured note\n"
    diags = parse_diagnostics(stdout=output, stderr="")
    assert len(diags) == 1
    assert diags[0].severity is DiagnosticSeverity.INFO
    assert diags[0].message == "random unstructured note"


def test_combines_stdout_and_stderr() -> None:
    diags = parse_diagnostics(
        stdout="info: started\n",
        stderr="error: failed at specs/a/spec.md\n",
    )
    severities = {d.severity for d in diags}
    assert DiagnosticSeverity.INFO in severities
    assert DiagnosticSeverity.ERROR in severities


def test_empty_output_returns_empty() -> None:
    assert parse_diagnostics(stdout="", stderr="") == ()


def test_warn_alias_maps_to_warning() -> None:
    diags = parse_diagnostics(stdout="warn: heads up\n", stderr="")
    assert len(diags) == 1
    assert diags[0].severity is DiagnosticSeverity.WARNING
