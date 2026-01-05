"""
Test examples: ContextEntity for Data Engineering, Data Science, and Big Data.

Demonstrates Blueprint + ContextEntity for NON-NARRATIVE use cases:
- Data pipeline design
- ML model training
- ETL workflows
- Big data processing
- Analytics systems

NO storytelling. NO human roles. Pure technical context entities.
"""

from cemaf.blueprint.builder import BlueprintBuilder
from cemaf.blueprint.schema import EntityType


class TestDataEngineeringUseCases:
    """Real-world data engineering examples using ContextEntity."""

    def test_etl_pipeline_blueprint(self) -> None:
        """ETL pipeline with data sources, transformations, and destinations as entities."""
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
            .add_technical_entity(
                name="postgres_source",
                description="PostgreSQL customer transactions database",
                domain="database",
                audience_level="expert",
                include_code_examples=True,
                traits=("relational", "ACID-compliant"),
                constraints=("read-only access", "connection pooling required"),
            )
            .add_technical_entity(
                name="salesforce_api",
                description="Salesforce CRM API for customer profiles",
                domain="api",
                audience_level="expert",
                include_code_examples=True,
                traits=("REST", "rate-limited", "paginated"),
                constraints=("API key rotation required", "max 100 requests/min"),
            )
            # Transformation logic as ANALYSIS entities
            .add_analysis_entity(
                name="deduplication_analyzer",
                description="Identify and merge duplicate customer records",
                methodology="quantitative",
                depth="comprehensive",
                focus_areas=("fuzzy matching", "merge rules", "conflict resolution"),
                traits=("deterministic", "auditable"),
            )
            .add_analysis_entity(
                name="enrichment_processor",
                description="Enrich customer data with demographics and behavior scores",
                methodology="mixed",
                depth="detailed",
                focus_areas=("demographic lookup", "behavior scoring", "segment assignment"),
            )
            # Data quality as VALIDATION entity
            .add_validation_entity(
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
            )
            # Target system as TECHNICAL entity
            .add_technical_entity(
                name="snowflake_warehouse",
                description="Snowflake data warehouse customer dimension table",
                domain="data_warehouse",
                audience_level="expert",
                include_diagrams=True,
                traits=("columnar", "partitioned", "clustered"),
                constraints=("SCD Type 2", "merge on customer_id"),
            )
            .with_instruction(
                "Design ETL pipeline that extracts from both sources, "
                "deduplicates records, enriches with additional attributes, "
                "validates data quality, and loads into Snowflake using MERGE. "
                "Include error handling, logging, and idempotency checks."
            )
            .with_tags("etl", "data-engineering", "production")
            .with_metadata(sla_hours=2, criticality="high")
            .build()
        )

        # Print the blueprint
        print(blueprint.to_prompt())

        # Assertions
        assert blueprint.id == "etl-pipeline-001"
        assert len(blueprint.entities) == 6

        # Verify entity types
        entity_types = [e.entity_type for e in blueprint.entities]
        assert EntityType.TECHNICAL in entity_types  # Sources and targets
        assert EntityType.ANALYSIS in entity_types  # Transformations
        assert EntityType.VALIDATION in entity_types  # Data quality

        # Verify no narrative/storytelling entities
        entity_names = [e.name for e in blueprint.entities]
        assert "postgres_source" in entity_names
        assert "deduplication_analyzer" in entity_names
        assert "data_quality_checker" in entity_names

        # Verify prompt generation includes all entities
        prompt = blueprint.to_prompt()
        assert "postgres_source" in prompt
        assert "Snowflake data warehouse" in prompt
        assert "merge on customer_id" in prompt.lower()  # Case-insensitive check

    def test_ml_model_training_blueprint(self) -> None:
        """ML training pipeline with datasets, models, and evaluation as entities."""
        blueprint = (
            BlueprintBuilder("ml-training-churn", "Customer Churn Prediction Model")
            .with_goal(
                "Train gradient boosting model to predict customer churn with 85%+ AUC",
                success_criteria=[
                    "AUC-ROC >= 0.85 on test set",
                    "Precision >= 0.75 for high-risk segment",
                    "Model explainability via SHAP values",
                    "Inference latency < 100ms",
                ],
                constraints=[
                    "No data leakage from future events",
                    "Balanced training set via oversampling",
                    "Cross-validation with temporal splits",
                ],
            )
            # Training data as TECHNICAL entity
            .add_technical_entity(
                name="feature_store",
                description="Pre-computed customer features from data warehouse",
                domain="data_science",
                audience_level="advanced",
                include_code_examples=True,
                traits=("versioned", "partitioned by date", "pre-aggregated"),
                constraints=("no future data", "7-day lag for feature stability"),
            )
            # Feature engineering as ANALYSIS entity
            .add_analysis_entity(
                name="feature_analyzer",
                description="Analyze feature importance and correlations",
                methodology="quantitative",
                depth="comprehensive",
                focus_areas=(
                    "correlation analysis",
                    "feature importance",
                    "multicollinearity detection",
                    "temporal stability",
                ),
                traits=("statistical", "visual"),
            )
            # Model comparison as COMPARATIVE entity
            .add_comparative_entity(
                name="model_comparator",
                description="Compare gradient boosting vs random forest vs neural network",
                dimensions=(
                    "AUC-ROC",
                    "precision",
                    "recall",
                    "training_time",
                    "inference_latency",
                    "memory_footprint",
                ),
                format="table",
                bias_awareness="objective",
                traits=("metric-based", "statistically significant"),
            )
            # Model validation as VALIDATION entity
            .add_validation_entity(
                name="model_validator",
                description="Validate model meets production requirements",
                validation_type="quality",
                rules=(
                    "auc_threshold_met",
                    "no_data_leakage",
                    "feature_drift_acceptable",
                    "prediction_distribution_valid",
                ),
                severity_levels=("blocker", "error", "warning"),
                auto_fix=False,
            )
            # Explainability as EDUCATIONAL entity
            .add_educational_entity(
                name="model_explainer",
                description="Generate SHAP explanations for model predictions",
                teaching_style="demonstration",
                knowledge_level="intermediate",
                include_examples=True,
                traits=("visual", "feature-level", "instance-level"),
            )
            .with_instruction(
                "Train XGBoost model on feature store data, "
                "perform hyperparameter tuning via Bayesian optimization, "
                "validate against holdout test set, "
                "generate SHAP explanations for top predictions, "
                "compare against baseline models. "
                "Output: trained model artifact, evaluation metrics, SHAP plots."
            )
            .with_tags("ml", "churn-prediction", "production-model")
            .build()
        )

        assert len(blueprint.entities) == 5
        assert all(e.entity_type != EntityType.CONTENT for e in blueprint.entities)  # No narrative

        # Verify diverse entity types for ML pipeline
        types = {e.entity_type for e in blueprint.entities}
        assert EntityType.TECHNICAL in types  # Feature store
        assert EntityType.ANALYSIS in types  # Feature analysis
        assert EntityType.COMPARATIVE in types  # Model comparison
        assert EntityType.VALIDATION in types  # Model validation
        assert EntityType.EDUCATIONAL in types  # Explainability

    def test_streaming_data_pipeline_blueprint(self) -> None:
        """Real-time streaming pipeline with Kafka, Flink, and monitoring."""
        blueprint = (
            BlueprintBuilder("streaming-events", "Real-time Event Processing Pipeline")
            .with_goal(
                "Process clickstream events in real-time with sub-second latency",
                success_criteria=[
                    "End-to-end latency < 500ms at p99",
                    "Throughput >= 100k events/sec",
                    "Zero data loss during failures",
                    "Exactly-once processing semantics",
                ],
            )
            # Kafka as TECHNICAL entity
            .add_technical_entity(
                name="kafka_source",
                description="Kafka topic for raw clickstream events",
                domain="streaming",
                audience_level="expert",
                include_code_examples=True,
                traits=("distributed", "partitioned", "replicated"),
                constraints=(
                    "3 replicas minimum",
                    "retention 7 days",
                    "compression: snappy",
                ),
            )
            # Stream processing as ANALYSIS entity
            .add_analysis_entity(
                name="session_aggregator",
                description="Window-based aggregation for user session metrics",
                methodology="quantitative",
                depth="comprehensive",
                focus_areas=(
                    "session boundaries",
                    "tumbling windows",
                    "late event handling",
                    "state management",
                ),
            )
            # Data quality monitoring as VALIDATION entity
            .add_validation_entity(
                name="stream_validator",
                description="Real-time data quality monitoring",
                validation_type="quality",
                rules=(
                    "schema_conformance",
                    "event_timestamp_valid",
                    "user_id_not_null",
                    "event_type_in_whitelist",
                ),
                auto_fix=True,  # Dead letter queue for invalid events
            )
            # Sink as TECHNICAL entity
            .add_technical_entity(
                name="timescaledb_sink",
                description="TimescaleDB for time-series analytics",
                domain="database",
                audience_level="advanced",
                include_diagrams=True,
                traits=("time-series optimized", "hypertables", "continuous aggregates"),
            )
            .with_instruction(
                "Design Flink streaming job that reads from Kafka, "
                "aggregates events into 5-minute tumbling windows, "
                "validates data quality, handles late arrivals with watermarks, "
                "maintains exactly-once semantics, and writes to TimescaleDB."
            )
            .with_tags("streaming", "real-time", "kafka", "flink")
            .build()
        )

        assert len(blueprint.entities) == 4
        # All technical/analytical - no storytelling
        prompt = blueprint.to_prompt()
        assert "Kafka" in prompt
        assert "Flink" in prompt
        assert "exactly-once" in prompt
        assert "watermarks" in prompt

    def test_data_warehouse_schema_design_blueprint(self) -> None:
        """Data warehouse dimensional model design."""
        blueprint = (
            BlueprintBuilder("dwh-schema-retail", "Retail Data Warehouse Star Schema")
            .with_goal(
                "Design star schema for retail analytics with 5+ fact tables",
                success_criteria=[
                    "Supports all analytics requirements",
                    "Query performance < 5 seconds for 95% of queries",
                    "Conforms to Kimball methodology",
                    "SCD Type 2 for slowly changing dimensions",
                ],
            )
            # Dimension tables as TECHNICAL entities
            .add_technical_entity(
                name="dim_customer",
                description="Customer dimension with SCD Type 2",
                domain="data_warehouse",
                audience_level="advanced",
                include_diagrams=True,
                traits=("SCD Type 2", "surrogate keys", "natural keys"),
                constraints=(
                    "effective_date and end_date for versioning",
                    "current_flag for active record",
                ),
            )
            .add_technical_entity(
                name="dim_product",
                description="Product hierarchy dimension",
                domain="data_warehouse",
                audience_level="advanced",
                traits=("hierarchical", "SCD Type 1", "conformed dimension"),
            )
            # Fact table as TECHNICAL entity
            .add_technical_entity(
                name="fact_sales",
                description="Sales transaction fact table",
                domain="data_warehouse",
                audience_level="advanced",
                include_diagrams=True,
                traits=("grain: transaction line item", "additive measures", "partitioned by date"),
                constraints=(
                    "foreign keys to all dimensions",
                    "degenerate dimension: order_number",
                ),
            )
            # Query pattern analysis as ANALYSIS entity
            .add_analysis_entity(
                name="query_pattern_analyzer",
                description="Analyze typical query patterns for optimization",
                methodology="quantitative",
                depth="detailed",
                focus_areas=(
                    "aggregation patterns",
                    "join cardinality",
                    "filter selectivity",
                    "index recommendations",
                ),
            )
            # Schema validation as VALIDATION entity
            .add_validation_entity(
                name="schema_validator",
                description="Validate star schema design best practices",
                validation_type="schema",
                rules=(
                    "fact_table_has_measures",
                    "dimensions_properly_conformed",
                    "surrogate_keys_consistent",
                    "referential_integrity_enforced",
                ),
            )
            .with_instruction(
                "Design complete star schema for retail analytics. "
                "Include customer, product, store, and time dimensions. "
                "Define fact tables for sales, inventory, and returns. "
                "Specify grain, measures, and dimension relationships. "
                "Include indexing and partitioning strategy."
            )
            .with_tags("data-warehouse", "dimensional-modeling", "star-schema")
            .build()
        )

        assert len(blueprint.entities) == 5
        # Verify warehouse-specific entities
        names = [e.name for e in blueprint.entities]
        assert "dim_customer" in names
        assert "fact_sales" in names
        assert "schema_validator" in names

    def test_data_quality_framework_blueprint(self) -> None:
        """Enterprise data quality monitoring framework."""
        blueprint = (
            BlueprintBuilder("dq-framework", "Enterprise Data Quality Framework")
            .with_goal(
                "Implement comprehensive data quality monitoring across all datasets",
                success_criteria=[
                    "100% of critical datasets monitored",
                    "Automated alerts for quality violations",
                    "Data lineage tracked for all tables",
                    "Quality score >= 95% for production data",
                ],
            )
            # Data profiling as ANALYSIS entity
            .add_analysis_entity(
                name="data_profiler",
                description="Statistical profiling of dataset characteristics",
                methodology="quantitative",
                depth="comprehensive",
                focus_areas=(
                    "column distributions",
                    "null percentages",
                    "cardinality",
                    "data types",
                    "outlier detection",
                ),
            )
            # Quality rules engine as VALIDATION entity
            .add_validation_entity(
                name="quality_rules_engine",
                description="Execute data quality rules across datasets",
                validation_type="quality",
                rules=(
                    "completeness_check",
                    "uniqueness_check",
                    "validity_check",
                    "consistency_check",
                    "timeliness_check",
                    "accuracy_check",
                ),
                severity_levels=("critical", "high", "medium", "low"),
                auto_fix=False,
            )
            # Lineage tracker as TECHNICAL entity
            .add_technical_entity(
                name="lineage_tracker",
                description="Track data lineage from source to consumption",
                domain="data_governance",
                audience_level="advanced",
                include_diagrams=True,
                traits=("column-level lineage", "DAG-based", "versioned"),
            )
            # Comparison against historical baseline as COMPARATIVE entity
            .add_comparative_entity(
                name="baseline_comparator",
                description="Compare current quality metrics against historical baselines",
                dimensions=(
                    "completeness",
                    "uniqueness",
                    "validity",
                    "timeliness",
                ),
                format="side-by-side",
                bias_awareness="objective",
            )
            .with_instruction(
                "Design data quality framework that profiles datasets, "
                "executes quality rules, tracks lineage, "
                "compares against baselines, and alerts on violations. "
                "Include dashboard design and alert routing logic."
            )
            .with_tags("data-quality", "data-governance", "monitoring")
            .build()
        )

        assert len(blueprint.entities) == 4
        # All entities are technical/analytical - no human roles
        types = [e.entity_type for e in blueprint.entities]
        assert EntityType.CONTENT not in types  # No storytelling!


class TestBigDataUseCases:
    """Big data processing examples using ContextEntity."""

    def test_spark_batch_processing_blueprint(self) -> None:
        """Large-scale batch processing with Apache Spark."""
        blueprint = (
            BlueprintBuilder("spark-batch-001", "Daily Log Processing Pipeline")
            .with_goal(
                "Process 100TB of daily logs using Spark on EMR cluster",
                success_criteria=[
                    "Complete processing within 4-hour batch window",
                    "Memory-efficient processing with 500GB cluster",
                    "Data quality validation at each stage",
                    "Outputs partitioned by date for efficient querying",
                ],
            )
            # Input data source as TECHNICAL entity
            .add_technical_entity(
                name="s3_raw_logs",
                description="S3 bucket with compressed JSON log files",
                domain="storage",
                audience_level="expert",
                traits=("gzip compressed", "partitioned by hour", "1TB per partition"),
                constraints=("read-only", "us-east-1 region", "standard storage class"),
            )
            # Spark job as ANALYSIS entity
            .add_analysis_entity(
                name="log_parser",
                description="Parse and enrich raw log entries",
                methodology="quantitative",
                depth="comprehensive",
                focus_areas=(
                    "user agent parsing",
                    "geo-IP lookup",
                    "session reconstruction",
                    "bot detection",
                ),
            )
            # Performance optimization as COMPARATIVE entity
            .add_comparative_entity(
                name="optimization_analyzer",
                description="Compare partitioning strategies for best performance",
                dimensions=(
                    "execution_time",
                    "shuffle_size",
                    "memory_usage",
                    "skew_factor",
                ),
                format="table",
            )
            .with_instruction(
                "Design Spark job that reads from S3, parses JSON logs, "
                "enriches with geo and user agent data, "
                "aggregates metrics, and writes partitioned Parquet files. "
                "Optimize for minimal shuffle and memory efficiency."
            )
            .with_tags("spark", "big-data", "batch-processing")
            .build()
        )

        assert len(blueprint.entities) == 3
        assert "s3_raw_logs" in [e.name for e in blueprint.entities]

    def test_distributed_system_architecture_blueprint(self) -> None:
        """Microservices architecture for data platform."""
        blueprint = (
            BlueprintBuilder("data-platform-arch", "Distributed Data Platform Architecture")
            .with_goal(
                "Design scalable microservices architecture for data platform",
                success_criteria=[
                    "Horizontally scalable to 1M requests/sec",
                    "99.99% uptime SLA",
                    "Multi-region active-active deployment",
                    "Sub-100ms API latency at p95",
                ],
            )
            # API Gateway as TECHNICAL entity
            .add_technical_entity(
                name="api_gateway",
                description="Kong API Gateway for request routing and auth",
                domain="infrastructure",
                audience_level="expert",
                include_diagrams=True,
                traits=("rate limiting", "JWT auth", "request/response transformation"),
            )
            # Microservices as TECHNICAL entities
            .add_technical_entity(
                name="query_service",
                description="GraphQL query service with DataLoader batching",
                domain="software",
                audience_level="advanced",
                include_code_examples=True,
                traits=("stateless", "horizontally scalable", "cache-aside pattern"),
            )
            .add_technical_entity(
                name="caching_layer",
                description="Redis cluster for query result caching",
                domain="infrastructure",
                audience_level="expert",
                traits=("distributed", "LRU eviction", "replication factor 3"),
            )
            # Load testing as VALIDATION entity
            .add_validation_entity(
                name="load_tester",
                description="Validate system performance under load",
                validation_type="quality",
                rules=(
                    "latency_p95_under_100ms",
                    "error_rate_below_0.1_percent",
                    "no_memory_leaks",
                    "graceful_degradation",
                ),
            )
            .with_instruction(
                "Design microservices architecture with API gateway, "
                "query services, caching layer, and monitoring. "
                "Include deployment topology, scaling policies, "
                "and disaster recovery procedures."
            )
            .with_tags("architecture", "microservices", "distributed-systems")
            .build()
        )

        assert len(blueprint.entities) == 4
        prompt = blueprint.to_prompt()
        assert "Kong" in prompt or "GraphQL" in prompt or "Redis" in prompt


# Integration test: Full pipeline from blueprint to LLM prompt
class TestEndToEndDataPipeline:
    """Test complete flow: Blueprint → ContextEntities → LLM Prompt."""

    def test_full_data_pipeline_to_prompt(self) -> None:
        """Generate LLM prompt for data pipeline design."""
        blueprint = (
            BlueprintBuilder("pipeline-design", "Modern Data Pipeline")
            .with_goal("Design production-ready data pipeline")
            .add_technical_entity(
                name="postgres_db",
                description="Source PostgreSQL database",
                domain="database",
            )
            .add_analysis_entity(
                name="transformer",
                description="Data transformation logic",
                methodology="quantitative",
            )
            .add_validation_entity(
                name="validator",
                description="Data quality validation",
                validation_type="schema",
            )
            .with_instruction("Design end-to-end pipeline with error handling")
            .build()
        )

        prompt = blueprint.to_prompt()

        # Verify prompt structure
        assert "## Goal" in prompt
        assert "## Context Entities" in prompt
        assert "## Instructions" in prompt

        # Verify entities appear in prompt
        assert "postgres_db" in prompt
        assert "transformer" in prompt
        assert "validator" in prompt

        # Verify entity types are shown
        assert "Type: Technical" in prompt
        assert "Type: Analysis" in prompt
        assert "Type: Validation" in prompt

        # Verify NO storytelling language
        assert "character" not in prompt.lower()
        assert "dialogue" not in prompt.lower()
        assert "narrative" not in prompt.lower()

        # This prompt can now be sent to an LLM!
        assert len(prompt) > 100  # Substantive prompt


class TestBlueprintContracts:
    """Test Blueprint contracts and policies for production data engineering."""

    def test_output_contract(self) -> None:
        """Test output contract specification."""
        blueprint = (
            BlueprintBuilder("test-output", "Output Contract Test")
            .with_goal("Generate structured output")
            .with_output_contract(
                format="json",
                required_sections=("schema", "data", "metadata"),
                must_include=("timestamp", "version"),
                forbidden=("debug_info", "internal_ids"),
            )
            .build()
        )

        assert blueprint.output_contract is not None
        assert blueprint.output_contract.format == "json"
        assert "schema" in blueprint.output_contract.required_sections
        assert "timestamp" in blueprint.output_contract.must_include
        assert "debug_info" in blueprint.output_contract.forbidden

        prompt = blueprint.to_prompt()
        assert "## Output Contract" in prompt
        assert "Format: json" in prompt
        assert "schema" in prompt

    def test_execution_policy(self) -> None:
        """Test execution policy specification."""
        blueprint = (
            BlueprintBuilder("test-exec", "Execution Policy Test")
            .with_goal("Incremental processing")
            .with_execution_policy(
                incremental_strategy="watermark",
                incremental_field="updated_at",
                max_retries=5,
                exactly_once=True,
            )
            .build()
        )

        assert blueprint.execution_policy is not None
        assert blueprint.execution_policy.incremental_strategy == "watermark"
        assert blueprint.execution_policy.incremental_field == "updated_at"
        assert blueprint.execution_policy.exactly_once is True

        prompt = blueprint.to_prompt()
        assert "## Execution Policy" in prompt
        assert "watermark" in prompt

    def test_security_policy(self) -> None:
        """Test security policy specification."""
        blueprint = (
            BlueprintBuilder("test-sec", "Security Policy Test")
            .with_goal("Secure PII handling")
            .with_security_policy(
                pii_fields=("email", "ssn"),
                encryption="at_rest_and_in_transit",
                compliance_frameworks=("GDPR", "HIPAA"),
            )
            .build()
        )

        assert blueprint.security_policy is not None
        assert "email" in blueprint.security_policy.pii_fields
        assert blueprint.security_policy.encryption == "at_rest_and_in_transit"

        prompt = blueprint.to_prompt()
        assert "## Security Policy" in prompt
        assert "GDPR" in prompt

    def test_data_contract_on_entity(self) -> None:
        """Test data contract on technical entity."""
        from cemaf.blueprint.schema import DataContract, SCD2Config

        data_contract = DataContract(
            schema_type="table",
            fields=("id", "name", "updated_at"),
            primary_key="id",
            incremental_field="updated_at",
            incremental_mode="upsert",
            scd2_config=SCD2Config(
                business_key="id",
                effective_from="valid_from",
                effective_to="valid_to",
            ),
        )

        blueprint = (
            BlueprintBuilder("test-dc", "Data Contract Test")
            .with_goal("Test data contracts")
            .add_technical_entity(
                name="test_table",
                description="Test table",
                domain="database",
                data_contract=data_contract,
            )
            .build()
        )

        assert blueprint.entities[0].data_contract is not None
        assert blueprint.entities[0].data_contract.primary_key == "id"
        assert blueprint.entities[0].data_contract.scd2_config is not None

        prompt = blueprint.to_prompt()
        assert "## Data Contract" in prompt
        assert "SCD2" in prompt

    def test_full_blueprint_serialization(self) -> None:
        """Test that blueprint with all features serializes correctly."""
        blueprint = (
            BlueprintBuilder("full-test", "Full Featured Blueprint")
            .with_goal("Test all features")
            .with_output_contract(format="yaml")
            .with_execution_policy(incremental_strategy="checkpoint")
            .with_security_policy(pii_fields=("email",))
            .build()
        )

        # Test serialization
        blueprint_dict = blueprint.to_dict()
        assert "output_contract" in blueprint_dict
        assert "execution_policy" in blueprint_dict
        assert "security_policy" in blueprint_dict

        # Test deserialization
        from cemaf.blueprint.schema import Blueprint

        restored = Blueprint.from_dict(blueprint_dict)
        assert restored.output_contract is not None
        assert restored.execution_policy is not None
        assert restored.security_policy is not None

    def test_backward_compatibility(self) -> None:
        """Test that blueprints without new features still work."""
        blueprint = (
            BlueprintBuilder("old-style", "Old Style Blueprint")
            .with_goal("Test backward compatibility")
            .add_technical_entity(name="old_entity", description="No contracts")
            .build()
        )

        # All new fields should be None
        assert blueprint.output_contract is None
        assert blueprint.execution_policy is None
        assert blueprint.security_policy is None
        assert blueprint.entities[0].data_contract is None

        # Should still serialize/deserialize
        blueprint_dict = blueprint.to_dict()
        from cemaf.blueprint.schema import Blueprint

        restored = Blueprint.from_dict(blueprint_dict)
        assert restored.id == "old-style"
