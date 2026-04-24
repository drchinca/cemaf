"""Unit tests for cemaf.security.masking."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import MemoryItem
from cemaf.security.masking import (
    ExclusionFilter,
    MaskingPipeline,
    MaskingRule,
    MaskingStrategy,
    PseudonymVault,
    create_masking_hook,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_item(value: dict) -> MemoryItem:
    """Create a minimal MemoryItem with the given value dict."""
    return MemoryItem(
        scope=MemoryScope.SESSION,
        key="test_key",
        value=value,
        confidence=Confidence(1.0),
    )


# ---------------------------------------------------------------------------
# MaskingStrategy.MASK
# ---------------------------------------------------------------------------


def test_mask_strategy_returns_stars() -> None:
    item = make_item({"ssn": "123-45-6789", "name": "Alice"})
    rule = MaskingRule(field="ssn", strategy=MaskingStrategy.MASK)
    pipeline = MaskingPipeline(rules=[rule])
    result = pipeline.apply(item)

    assert result.value["ssn"] == "*****"
    assert result.value["name"] == "Alice"  # unchanged


# ---------------------------------------------------------------------------
# MaskingStrategy.ANONYMIZE
# ---------------------------------------------------------------------------


def test_anonymize_strategy_is_deterministic() -> None:
    secret = b"supersecretkey!!"
    vault = PseudonymVault(secret_key=secret)
    rule = MaskingRule(field="email", strategy=MaskingStrategy.ANONYMIZE)
    pipeline = MaskingPipeline(rules=[rule], vault=vault)

    item = make_item({"email": "alice@example.com"})
    result1 = pipeline.apply(item)
    result2 = pipeline.apply(item)

    # Same input + same key => same pseudonym
    assert result1.value["email"] == result2.value["email"]
    # Pseudonym is wrapped in angle brackets
    pseudo = result1.value["email"]
    assert isinstance(pseudo, str)
    assert pseudo.startswith("<") and pseudo.endswith(">")


def test_anonymize_different_secrets_differ() -> None:
    vault_a = PseudonymVault(secret_key=b"key_alpha_111111")
    vault_b = PseudonymVault(secret_key=b"key_beta_2222222")
    rule = MaskingRule(field="phone", strategy=MaskingStrategy.ANONYMIZE)

    item = make_item({"phone": "+1-555-0100"})
    result_a = MaskingPipeline(rules=[rule], vault=vault_a).apply(item)
    result_b = MaskingPipeline(rules=[rule], vault=vault_b).apply(item)

    # Different keys should (with overwhelming probability) produce different pseudonyms
    assert result_a.value["phone"] != result_b.value["phone"]


# ---------------------------------------------------------------------------
# MaskingStrategy.REDACT
# ---------------------------------------------------------------------------


def test_redact_removes_field() -> None:
    item = make_item({"secret": "hunter2", "public": "hello"})
    rule = MaskingRule(field="secret", strategy=MaskingStrategy.REDACT)
    pipeline = MaskingPipeline(rules=[rule])
    result = pipeline.apply(item)

    assert "secret" not in result.value
    assert result.value["public"] == "hello"


# ---------------------------------------------------------------------------
# Multi-rule pipeline
# ---------------------------------------------------------------------------


def test_pipeline_applies_multiple_rules() -> None:
    vault = PseudonymVault(secret_key=b"multi_rule_secret")
    rules = [
        MaskingRule(field="ssn", strategy=MaskingStrategy.MASK),
        MaskingRule(field="name", strategy=MaskingStrategy.ANONYMIZE),
        MaskingRule(field="internal_id", strategy=MaskingStrategy.REDACT),
    ]
    pipeline = MaskingPipeline(rules=rules, vault=vault)
    item = make_item({
        "ssn": "123-45-6789",
        "name": "Bob",
        "internal_id": "EMP-99",
        "department": "Engineering",
    })
    result = pipeline.apply(item)

    assert result.value["ssn"] == "*****"
    assert result.value["name"].startswith("<")
    assert "internal_id" not in result.value
    assert result.value["department"] == "Engineering"


# ---------------------------------------------------------------------------
# Unaffected fields
# ---------------------------------------------------------------------------


def test_unaffected_fields_unchanged() -> None:
    rule = MaskingRule(field="secret_token", strategy=MaskingStrategy.MASK)
    pipeline = MaskingPipeline(rules=[rule])
    item = make_item({
        "secret_token": "abc123",
        "username": "carol",
        "role": "admin",
        "score": 42,
    })
    result = pipeline.apply(item)

    # Only 'secret_token' should change
    assert result.value["username"] == "carol"
    assert result.value["role"] == "admin"
    assert result.value["score"] == 42


# ---------------------------------------------------------------------------
# ExclusionFilter
# ---------------------------------------------------------------------------


def test_exclusion_filter_matches() -> None:
    f = ExclusionFilter(field="status", excluded_values=("deleted", "archived"))
    item = make_item({"status": "deleted", "content": "old post"})
    assert f.matches(item) is True


def test_exclusion_filter_no_match() -> None:
    f = ExclusionFilter(field="status", excluded_values=("deleted", "archived"))
    item = make_item({"status": "active", "content": "live post"})
    assert f.matches(item) is False


def test_exclusion_filter_missing_field_no_match() -> None:
    """A field missing from value does not trigger exclusion."""
    f = ExclusionFilter(field="classification", excluded_values=("TOP_SECRET",))
    item = make_item({"title": "annual report"})
    # item.value.get("classification") returns None, which is not in excluded_values
    assert f.matches(item) is False


# ---------------------------------------------------------------------------
# create_masking_hook
# ---------------------------------------------------------------------------


def test_create_masking_hook_returns_callable() -> None:
    rule = MaskingRule(field="api_key", strategy=MaskingStrategy.MASK)
    pipeline = MaskingPipeline(rules=[rule])
    hook = create_masking_hook(pipeline)

    assert callable(hook)

    item = make_item({"api_key": "sk-secret", "model": "gpt-4"})
    result = hook(item)

    assert isinstance(result, MemoryItem)
    assert result.value["api_key"] == "*****"
    assert result.value["model"] == "gpt-4"


# ---------------------------------------------------------------------------
# ANONYMIZE without vault raises RuntimeError
# ---------------------------------------------------------------------------


def test_anonymize_without_vault_raises() -> None:
    rule = MaskingRule(field="name", strategy=MaskingStrategy.ANONYMIZE)
    pipeline = MaskingPipeline(rules=[rule], vault=None)
    item = make_item({"name": "Dave"})

    with pytest.raises(RuntimeError, match="PseudonymVault"):
        pipeline.apply(item)
