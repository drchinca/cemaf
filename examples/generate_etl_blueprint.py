"""
Generate ETL Blueprint example and export to JSON.

Run: uv run python examples/generate_etl_blueprint.py
"""

import json

from cemaf.blueprint.builder import BlueprintBuilder
from cemaf.blueprint.contracts import DataContract, RateLimitConfig, SCD2Config
from cemaf.blueprint.entities import ContextEntity


def main() -> None:
    """Generate ETL pipeline blueprint and export to JSON."""
    blueprint = (
        BlueprintBuilder("etl-pipeline-001", "Customer Data ETL Pipeline")
        .with_goal(
            "Extract customer data from multiple sources, transform, and load into data warehouse",
            success_criteria=[
                "All source systems integrated",
                "Data quality validation passes",
                "Target schema matches requirements",
                "Pipeline completes within 2-hour window",
            ],
            constraints=[
                "PII data must be encrypted",
                "No data loss during transformation",
                "Idempotent operations for retry safety",
            ],
        )
        .with_description("Production ETL pipeline for customer 360 view")
        # Data sources as TECHNICAL entities
        .add_entity(
            ContextEntity.technical(
                name="postgres_source",
                description="PostgreSQL customer transactions database",
                domain="database",
                audience_level="expert",
                include_code_examples=True,
                traits=("relational", "ACID-compliant"),
                constraints=("read-only access", "connection pooling required"),
                token_priority=9,
            ),
            data_contract=DataContract(
                schema_type="table",
                fields=("customer_id", "transaction_id", "amount", "updated_at"),
                primary_key="customer_id",
                incremental_field="updated_at",
                incremental_mode="upsert",
            ),
        )
        .add_entity(
            ContextEntity.technical(
                name="salesforce_api",
                description="Salesforce CRM API for customer profiles",
                domain="api",
                audience_level="expert",
                include_code_examples=True,
                traits=("REST", "rate-limited", "paginated"),
                constraints=("API key rotation required", "max 100 requests/min"),
                token_priority=9,
            ),
            data_contract=DataContract(
                schema_type="api",
                fields=("Id", "Email", "Phone", "FirstName", "LastName", "LastModifiedDate"),
                primary_key="Id",
                incremental_field="LastModifiedDate",
                rate_limit=RateLimitConfig(
                    max_requests_per_minute=100,
                    on_429_action="backoff_exponential",
                ),
            ),
        )
        # Transformation logic as ANALYSIS entities
        .add_entity(
            ContextEntity.analysis(
                name="deduplication_analyzer",
                description="Identify and merge duplicate customer records",
                methodology="quantitative",
                depth="comprehensive",
                focus_areas=("fuzzy matching", "merge rules", "conflict resolution"),
                traits=("deterministic", "auditable"),
                token_priority=7,
            )
        )
        .add_entity(
            ContextEntity.analysis(
                name="enrichment_processor",
                description="Enrich customer data with demographics and behavior scores",
                methodology="mixed",
                depth="detailed",
                focus_areas=("demographic lookup", "behavior scoring", "segment assignment"),
                token_priority=7,
            )
        )
        # Data quality as VALIDATION entity
        .add_entity(
            ContextEntity.validation(
                name="data_quality_checker",
                description="Validate data quality before warehouse load",
                validation_type="schema",
                rules=(
                    "email_format_valid",
                    "phone_number_normalized",
                    "required_fields_present",
                    "referential_integrity",
                ),
                severity_levels=("critical", "error", "warning"),
                auto_fix=False,
                traits=("strict", "blocking"),
                token_priority=9,
            )
        )
        # Target system as TECHNICAL entity
        .add_entity(
            ContextEntity.technical(
                name="snowflake_warehouse",
                description="Snowflake data warehouse customer dimension table",
                domain="data_warehouse",
                audience_level="expert",
                include_diagrams=True,
                traits=("columnar", "partitioned", "clustered"),
                constraints=("SCD Type 2", "merge on customer_id"),
                token_priority=9,
            ),
            data_contract=DataContract(
                schema_type="table",
                fields=(
                    "customer_sk",
                    "customer_id",
                    "email",
                    "phone",
                    "valid_from",
                    "valid_to",
                    "is_current",
                ),
                primary_key="customer_sk",
                scd2_config=SCD2Config(
                    business_key="customer_id",
                    effective_from="valid_from",
                    effective_to="valid_to",
                    is_current="is_current",
                    record_hash="attr_hash",
                ),
            ),
        )
        .with_instruction(
            "Design ETL pipeline that extracts from both sources, "
            "deduplicates records, enriches with additional attributes, "
            "validates data quality, and loads into Snowflake using MERGE. "
            "Include error handling, logging, and idempotency checks."
        )
        .with_tags("etl", "data-engineering", "production")
        .with_metadata(sla_hours=2, criticality="high")
        .with_output_contract(
            format="yaml",
            required_sections=(
                "pipeline_architecture",
                "data_flow",
                "error_handling",
                "monitoring",
            ),
            must_include=(
                "Complete ETL pipeline code",
                "Data quality validation rules",
                "Idempotency implementation",
                "SCD2 MERGE logic",
            ),
            forbidden=("hardcoded credentials", "unencrypted PII"),
        )
        .with_execution_policy(
            incremental_strategy="watermark",
            incremental_field="updated_at",
            checkpoint_location="s3://my-bucket/checkpoints/customer-etl/",
            idempotency_key="run_id",
            max_retries=3,
            retry_on=("rate_limit", "transient_network", "timeout"),
            fail_on=("data_quality_fail", "schema_mismatch"),
            exactly_once=False,
        )
        .with_security_policy(
            pii_fields=("email", "phone_number", "ssn", "address"),
            encryption="at_rest_and_in_transit",
            secret_rotation=True,
            secret_provider="kms",
            secret_rotation_days=90,
            compliance_frameworks=("GDPR", "CCPA"),
        )
        .build()
    )

    # Export to JSON
    blueprint_dict = blueprint.to_dict()

    # Save to file
    with open("examples/etl_blueprint.json", "w") as f:
        json.dump(blueprint_dict, f, indent=2)

    print("✅ Blueprint JSON saved to: examples/etl_blueprint.json")

    # Also print the LLM-ready prompt
    print("\n" + "=" * 80)
    print("LLM-READY PROMPT:")
    print("=" * 80)
    print(blueprint.to_prompt())

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("=" * 80)
    print(f"Blueprint ID: {blueprint.id}")
    print(f"Total Entities: {len(blueprint.entities)}")
    print(f"Entity Types: {({e.entity_type.value for e in blueprint.entities})}")
    print(f"Entity Names: {[e.name for e in blueprint.entities]}")


if __name__ == "__main__":
    main()
