"""
Factory functions for persistence store components.

Provides convenient ways to create persistence stores with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_X_store_from_config()
    functions include clear "EXTEND HERE" sections where you can add
    your own store implementations (PostgreSQL, MongoDB, DynamoDB, etc.).
"""

import os

from cemaf.config.protocols import Settings
from cemaf.persistence.protocols import (
    ArtifactStore,
    ContentStore,
    ProjectStore,
    RunStore,
)


def create_project_store_from_config(settings: Settings | None = None) -> ProjectStore:
    """
    Create ProjectStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_PROJECT_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string (for database backends)

    Returns:
        Configured ProjectStore instance

    Example:
        # From environment
        store = create_project_store_from_config()
    """
    backend = os.getenv("CEMAF_PERSISTENCE_PROJECT_STORE_BACKEND", "mock")

    # BUILT-IN IMPLEMENTATIONS
    # Note: No mock implementation exists yet. This is an extension point.

    # ============================================================================
    # EXTEND HERE: Bring Your Own Project Store
    # ============================================================================
    # This is the extension point for custom project store backends.
    #
    # To add your own implementation:
    # 1. Implement the ProjectStore protocol (see cemaf.persistence.protocols)
    # 2. Add your backend case below
    # 3. Read configuration from environment variables
    #
    # Example (PostgreSQL):
    #   if backend == "postgres":
    #       from your_package import PostgresProjectStore
    #       db_url = os.getenv("DATABASE_URL")
    #       return PostgresProjectStore(connection_string=db_url)
    #
    # Example (MongoDB):
    #   elif backend == "mongodb":
    #       from your_package import MongoProjectStore
    #       mongo_uri = os.getenv("MONGODB_URI")
    #       db_name = os.getenv("MONGODB_DATABASE", "cemaf")
    #       return MongoProjectStore(uri=mongo_uri, database=db_name)
    #
    # Example (DynamoDB):
    #   elif backend == "dynamodb":
    #       from your_package import DynamoDBProjectStore
    #       table_name = os.getenv("DYNAMODB_PROJECTS_TABLE", "cemaf_projects")
    #       region = os.getenv("AWS_REGION", "us-east-1")
    #       return DynamoDBProjectStore(table_name=table_name, region=region)
    #
    # Example (In-Memory for testing):
    #   elif backend == "memory":
    #       from your_package import InMemoryProjectStore
    #       return InMemoryProjectStore()
    # ============================================================================

    raise ValueError(
        f"Unsupported project store backend: {backend}. "
        f"No built-in implementations available. "
        f"To add your own, extend create_project_store_from_config() "
        f"in cemaf/persistence/factories.py"
    )


def create_artifact_store_from_config(settings: Settings | None = None) -> ArtifactStore:
    """
    Create ArtifactStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_ARTIFACT_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string

    Returns:
        Configured ArtifactStore instance
    """
    backend = os.getenv("CEMAF_PERSISTENCE_ARTIFACT_STORE_BACKEND", "mock")

    # ============================================================================
    # EXTEND HERE: Bring Your Own Artifact Store
    # ============================================================================
    # Example (PostgreSQL with blob storage):
    #   if backend == "postgres":
    #       from your_package import PostgresArtifactStore
    #       db_url = os.getenv("DATABASE_URL")
    #       return PostgresArtifactStore(connection_string=db_url)
    #
    # Example (S3):
    #   elif backend == "s3":
    #       from your_package import S3ArtifactStore
    #       bucket = os.getenv("S3_ARTIFACTS_BUCKET")
    #       region = os.getenv("AWS_REGION", "us-east-1")
    #       return S3ArtifactStore(bucket=bucket, region=region)
    # ============================================================================

    raise ValueError(
        f"Unsupported artifact store backend: {backend}. "
        f"To add your own, extend create_artifact_store_from_config()"
    )


def create_content_store_from_config(settings: Settings | None = None) -> ContentStore:
    """
    Create ContentStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_CONTENT_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string

    Returns:
        Configured ContentStore instance
    """
    backend = os.getenv("CEMAF_PERSISTENCE_CONTENT_STORE_BACKEND", "mock")

    # ============================================================================
    # EXTEND HERE: Bring Your Own Content Store
    # ============================================================================
    # Example (PostgreSQL):
    #   if backend == "postgres":
    #       from your_package import PostgresContentStore
    #       db_url = os.getenv("DATABASE_URL")
    #       return PostgresContentStore(connection_string=db_url)
    #
    # Example (MongoDB):
    #   elif backend == "mongodb":
    #       from your_package import MongoContentStore
    #       mongo_uri = os.getenv("MONGODB_URI")
    #       return MongoContentStore(uri=mongo_uri)
    # ============================================================================

    raise ValueError(
        f"Unsupported content store backend: {backend}. "
        f"To add your own, extend create_content_store_from_config()"
    )


def create_run_store_from_config(settings: Settings | None = None) -> RunStore:
    """
    Create RunStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_RUN_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string

    Returns:
        Configured RunStore instance
    """
    backend = os.getenv("CEMAF_PERSISTENCE_RUN_STORE_BACKEND", "mock")

    # ============================================================================
    # EXTEND HERE: Bring Your Own Run Store
    # ============================================================================
    # Example (PostgreSQL):
    #   if backend == "postgres":
    #       from your_package import PostgresRunStore
    #       db_url = os.getenv("DATABASE_URL")
    #       return PostgresRunStore(connection_string=db_url)
    #
    # Example (Time-series database):
    #   elif backend == "timescale":
    #       from your_package import TimescaleRunStore
    #       db_url = os.getenv("TIMESCALE_URL")
    #       return TimescaleRunStore(connection_string=db_url)
    # ============================================================================

    raise ValueError(
        f"Unsupported run store backend: {backend}. To add your own, extend create_run_store_from_config()"
    )
