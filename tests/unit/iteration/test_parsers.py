"""Parser tests — SPEC-08 §4 scenarios + Property 1 (determinism)."""

from __future__ import annotations

import pytest

from cemaf.iteration.parsers import (
    MypyParser,
    PytestParser,
    RuffParser,
    ShellFallbackParser,
)
from cemaf.iteration.types import FailureKind
from cemaf.sandbox.shell import ShellResult


def _shell(*, stdout: str = "", stderr: str = "", command: str, exit_code: int = 1) -> ShellResult:
    return ShellResult(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)


PYTEST_OUTPUT = """\
============================= test session starts ==============================
collected 2 items

tests/unit/test_calc.py::test_add PASSED                                  [ 50%]
tests/unit/test_calc.py::test_sub FAILED                                  [100%]

=================================== FAILURES ===================================
__________________________________ test_sub ____________________________________

    def test_sub():
>       assert 2 - 1 == 0
E       assert 1 == 0

tests/unit/test_calc.py:7: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_calc.py::test_sub - assert 1 == 0
"""


class TestPytestParser:
    def test_parses_failed_test(self) -> None:
        parser = PytestParser()
        result = _shell(stdout=PYTEST_OUTPUT, command="uv run pytest -q")
        signal = parser.parse(result)
        assert signal is not None
        assert signal.kind is FailureKind.TEST_FAILURE
        assert len(signal.items) == 1
        assert signal.items[0].file == "tests/unit/test_calc.py"
        assert signal.items[0].line == 7
        assert "test_sub" in (signal.items[0].rule or "")
        assert "assert 1 == 0" in signal.items[0].message

    def test_parse_is_deterministic(self) -> None:
        parser = PytestParser()
        result = _shell(stdout=PYTEST_OUTPUT, command="uv run pytest -q")
        assert parser.parse(result) == parser.parse(result)

    def test_success_returns_none(self) -> None:
        parser = PytestParser()
        result = ShellResult(command="uv run pytest -q", exit_code=0, stdout="passed")
        assert parser.parse(result) is None

    def test_truncates_at_max_items(self) -> None:
        lines = "\n".join(f"FAILED tests/unit/test_x.py::test_n{i} - assert {i} == 0" for i in range(50))
        parser = PytestParser(max_items=10)
        result = _shell(stdout=lines, command="pytest")
        signal = parser.parse(result)
        assert signal is not None
        assert len(signal.items) == 10
        assert signal.truncated is True

    def test_matches_only_failures(self) -> None:
        parser = PytestParser()
        success = ShellResult(command="pytest", exit_code=0)
        assert parser.matches(success) is False


class TestRuffParser:
    def test_parses_violations(self) -> None:
        parser = RuffParser()
        out = "src/foo.py:12:1: F401 `os` imported but unused\nsrc/bar.py:99:80: E501 Line too long\n"
        signal = parser.parse(_shell(stdout=out, command="ruff check ."))
        assert signal is not None
        assert signal.kind is FailureKind.LINT_FAILURE
        rules = {item.rule for item in signal.items}
        assert rules == {"F401", "E501"}

    def test_deterministic(self) -> None:
        parser = RuffParser()
        result = _shell(stdout="src/x.py:1:1: F401 unused\n", command="ruff")
        assert parser.parse(result) == parser.parse(result)


class TestMypyParser:
    def test_parses_type_error(self) -> None:
        parser = MypyParser()
        out = "src/foo.py:12: error: Incompatible types  [assignment]\n"
        signal = parser.parse(_shell(stdout=out, command="mypy src/"))
        assert signal is not None
        assert signal.kind is FailureKind.TYPE_FAILURE
        assert signal.items[0].file == "src/foo.py"
        assert signal.items[0].line == 12
        assert signal.items[0].rule == "assignment"


class TestShellFallback:
    def test_matches_any_failure(self) -> None:
        parser = ShellFallbackParser()
        assert parser.matches(_shell(command="anything")) is True

    def test_uses_stderr_for_summary(self) -> None:
        parser = ShellFallbackParser()
        signal = parser.parse(_shell(stderr="boom: missing module", command="python x.py"))
        assert signal is not None
        assert signal.kind is FailureKind.UNKNOWN
        assert "boom" in signal.summary

    def test_truncates_long_stderr(self) -> None:
        parser = ShellFallbackParser()
        long = "x" * 10_000
        signal = parser.parse(_shell(stderr=long, command="cmd"))
        assert signal is not None
        assert signal.truncated is True
        assert len(signal.summary) <= 512


@pytest.mark.parametrize(
    "parser,output,command",
    [
        (PytestParser(), PYTEST_OUTPUT, "pytest"),
        (RuffParser(), "src/x.py:1:1: F401 unused\n", "ruff"),
        (MypyParser(), "src/x.py:1: error: bad [assignment]", "mypy"),
    ],
)
def test_property_1_determinism(parser, output: str, command: str) -> None:
    """SPEC-08 Property 1: same input ⇒ same FailureSignal."""
    result = _shell(stdout=output, command=command)
    assert parser.parse(result) == parser.parse(result)
