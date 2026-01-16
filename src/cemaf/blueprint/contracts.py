"""
Data contracts for blueprint entities.

Defines schema specifications, processing requirements, and configurations
for data engineering use cases.
"""

from typing import Literal

from pydantic import BaseModel, Field

from cemaf.core.types import JSON


class SCD2Config(BaseModel):
    """Configuration for Slowly Changing Dimension Type 2."""

    model_config = {"frozen": True}

    business_key: str  # Natural key field
    effective_from: str = "valid_from_ts"
    effective_to: str = "valid_to_ts"
    is_current: str = "is_current"
    record_hash: str = "attr_hash"  # For change detection


class RateLimitConfig(BaseModel):
    """Configuration for API rate limiting."""

    model_config = {"frozen": True}

    max_requests_per_minute: int = 100
    max_requests_per_day: int = 10000
    on_429_action: Literal["backoff_exponential", "backoff_linear", "fail"] = "backoff_exponential"
    backoff_initial_delay_seconds: float = 1.0
    backoff_max_delay_seconds: float = 300.0


class DataContract(BaseModel):
    """
    Defines data schema, keys, and processing requirements for an entity.

    Specifies table/object structure, identity strategies, and processing
    patterns for data engineering use cases.
    """

    model_config = {"frozen": True}

    # Schema definition
    schema_type: Literal["table", "object", "file", "stream", "api"] = "table"
    fields: tuple[str, ...] = ()  # Column/field names
    primary_key: str = ""
    partition_keys: tuple[str, ...] = ()

    # Incremental processing
    incremental_field: str = ""  # Watermark field (e.g., "updated_at")
    incremental_mode: Literal["append", "upsert", "full_refresh"] = "append"

    # Deduplication and identity
    dedup_keys: tuple[str, ...] = ()  # For deduplication
    match_features: tuple[str, ...] = ()  # For fuzzy matching

    # SCD2 configuration (for dimension tables)
    scd2_config: SCD2Config | None = None

    # Rate limiting (for APIs)
    rate_limit: RateLimitConfig | None = None

    # Data quality
    required_fields: tuple[str, ...] = ()
    nullable_fields: tuple[str, ...] = ()

    metadata: JSON = Field(default_factory=dict)
