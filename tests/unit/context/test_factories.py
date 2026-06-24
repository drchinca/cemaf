"""Tests for context factory helpers."""

from cemaf.context.factories import create_token_budget


def test_create_token_budget_uses_explicit_max_tokens() -> None:
    budget = create_token_budget(max_tokens=1234)

    assert budget.max_tokens == 1234


def test_create_token_budget_can_derive_from_model() -> None:
    budget = create_token_budget(model="gpt-4o")

    assert budget.max_tokens == 128_000
