"""Public blueprint package exports."""

from __future__ import annotations


def test_policy_and_contract_models_are_top_level_exports() -> None:
    from cemaf.blueprint import (
        DataContract,
        ExecutionPolicy,
        OutputContract,
        RateLimitConfig,
        SCD2Config,
        SecurityPolicy,
    )

    assert DataContract(schema_type="object", fields=("title",)).fields == ("title",)
    assert RateLimitConfig(max_requests_per_minute=60).max_requests_per_minute == 60
    assert SCD2Config(business_key="id").business_key == "id"
    assert OutputContract(format="json").format == "json"
    assert ExecutionPolicy(max_retries=2).max_retries == 2
    assert SecurityPolicy(encryption="at_rest").encryption == "at_rest"
