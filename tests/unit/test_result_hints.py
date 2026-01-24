"""
Tests for the Result pattern in cemaf.core.result.
"""

from cemaf.core.result import Result


def test_result_with_hints():
    """Test that Result can carry structured hints for agents."""
    hints = [
        {"action": "retry", "reason": "rate_limit", "suggestion": "wait 5s"},
        {"action": "summarize", "reason": "token_limit", "suggestion": "use summarizer gate"},
    ]

    # Test fail with hints
    result = Result.fail("Operation failed", hints=hints)
    assert not result.success
    assert result.hints == hints

    # Test ok with hints (though less common)
    result_ok = Result.ok(
        "Success",
        hints=[
            {
                "action": "none",
                "reason": "success",
                "suggestion": "continue",
            }
        ],
    )
    assert result_ok.success
    assert len(result_ok.hints) == 1


def test_result_with_hint_builder():
    """Test the with_hint builder method."""
    result = (
        Result.fail("Token limit exceeded")
        .with_hint(action="summarize", reason="context_too_large", suggestion="Add a SummarizerGate")
        .with_hint(action="increase_budget", reason="hard_limit", suggestion="Set budget to 4000")
    )

    assert not result.success
    assert len(result.hints) == 2
    assert result.hints[0]["action"] == "summarize"
    assert result.hints[1]["action"] == "increase_budget"


def test_result_from_exception_with_hints():
    """Test that from_exception can include hints if provided."""
    try:
        raise ValueError("Too many tokens")
    except ValueError as e:
        result = Result.from_exception(e).with_hint(
            action="summarize", reason="value_error", suggestion="Check token count"
        )

    assert not result.success
    assert result.error == "Too many tokens"
    assert len(result.hints) == 1
    assert result.hints[0]["action"] == "summarize"
