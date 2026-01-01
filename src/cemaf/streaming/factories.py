"""
Factory functions for streaming components.

Provides convenient ways to create streaming processors with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.streaming.sse import SSEStreamProcessor


def create_sse_stream_processor(
    buffer_size: int = 1000,
    chunk_timeout_seconds: float = 30.0,
) -> SSEStreamProcessor:
    """
    Factory for SSEStreamProcessor with sensible defaults.

    Args:
        buffer_size: Buffer size for streaming
        chunk_timeout_seconds: Timeout for chunk delivery

    Returns:
        Configured SSEStreamProcessor instance

    Example:
        # With defaults
        processor = create_sse_stream_processor()

        # Custom configuration
        processor = create_sse_stream_processor(buffer_size=500)
    """
    return SSEStreamProcessor(
        buffer_size=buffer_size,
        chunk_timeout_seconds=chunk_timeout_seconds,
    )


def create_sse_stream_processor_from_config(settings: Settings | None = None) -> SSEStreamProcessor:
    """
    Create SSEStreamProcessor from environment configuration.

    Reads from environment variables:
    - CEMAF_STREAMING_BUFFER_SIZE: Buffer size (default: 1000)
    - CEMAF_STREAMING_CHUNK_TIMEOUT_SECONDS: Chunk timeout (default: 30.0)

    Returns:
        Configured SSEStreamProcessor instance

    Example:
        # From environment
        processor = create_sse_stream_processor_from_config()
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    buffer_size = int(os.getenv("CEMAF_STREAMING_BUFFER_SIZE", "1000"))
    chunk_timeout = float(os.getenv("CEMAF_STREAMING_CHUNK_TIMEOUT_SECONDS", "30.0"))

    return create_sse_stream_processor(
        buffer_size=buffer_size,
        chunk_timeout_seconds=chunk_timeout,
    )
