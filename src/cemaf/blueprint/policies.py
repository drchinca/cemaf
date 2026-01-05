"""
Blueprint policies for production use cases.

Defines contracts and policies for output format, execution semantics,
and security requirements.
"""

from typing import Literal

from pydantic import BaseModel, Field

from cemaf.core.types import JSON

# Type aliases
OutputFormat = Literal["json", "yaml", "markdown", "python", "sql"]
RequiredSections = tuple[str, ...]


class OutputContract(BaseModel):
    """
    Defines expected deliverables and output format.

    Specifies format, required sections, and content requirements to prevent
    model from responding with unstructured prose instead of requested output.
    """

    model_config = {"frozen": True}

    format: OutputFormat = "yaml"
    required_sections: RequiredSections = ()
    must_include: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    schema_definition: str = ""  # Optional JSON Schema or YAML schema
    metadata: JSON = Field(default_factory=dict)


class ExecutionPolicy(BaseModel):
    """
    Defines execution semantics for idempotency and retry behavior.

    Specifies checkpoint strategy, retry conditions, and failure handling
    for production data pipelines.
    """

    model_config = {"frozen": True}

    # Incremental processing strategy
    incremental_strategy: Literal["full", "watermark", "checkpoint"] = "full"
    incremental_field: str = ""  # e.g., "updated_at", "event_timestamp"
    checkpoint_location: str = ""  # e.g., "s3://bucket/checkpoints"

    # Idempotency
    idempotency_key: str = "run_id"  # Field to ensure idempotent operations
    deterministic_batching: bool = True  # Use consistent batch keys

    # Retry semantics
    max_retries: int = 3
    retry_on: tuple[str, ...] = ("rate_limit", "transient_network", "timeout")
    fail_on: tuple[str, ...] = ("data_quality_fail", "schema_mismatch")

    # Execution mode
    exactly_once: bool = False  # vs effectively-once (at-least-once + idempotency)

    metadata: JSON = Field(default_factory=dict)


class SecurityPolicy(BaseModel):
    """
    Defines security requirements for data handling.

    Specifies PII handling, encryption requirements, and secret management
    for compliance with data protection regulations.
    """

    model_config = {"frozen": True}

    pii_fields: tuple[str, ...] = ()  # List of PII field names
    encryption: Literal["at_rest", "in_transit", "at_rest_and_in_transit", "none"] = "none"

    # Secret management
    secret_rotation: bool = False
    secret_provider: Literal["kms", "vault", "env", "none"] = "none"
    secret_rotation_days: int = 90

    # Compliance
    compliance_frameworks: tuple[str, ...] = ()  # e.g., ("GDPR", "HIPAA", "SOC2")

    metadata: JSON = Field(default_factory=dict)
