"""
Factory functions for citation tracking components.

Provides convenient ways to create citation trackers with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_citation_tracker_from_config()
    function includes a clear "EXTEND HERE" section where you can add
    your own tracker implementations.
"""

import os

from cemaf.citation.mock import MockCitationTracker
from cemaf.citation.protocols import CitationTracker as CitationTrackerProtocol
from cemaf.citation.tracker import CitationTracker
from cemaf.config.protocols import Settings


def create_citation_tracker(
    backend: str = "default",
    enable_tracking: bool = True,
    require_citations: bool = False,
) -> CitationTrackerProtocol:
    """
    Factory for CitationTracker with sensible defaults.

    Args:
        backend: Tracker backend (default, mock)
        enable_tracking: Enable citation tracking
        require_citations: Require citations for all claims

    Returns:
        Configured CitationTracker instance

    Example:
        # Default tracker
        tracker = create_citation_tracker()

        # With required citations
        tracker = create_citation_tracker(require_citations=True)

        # Mock for testing
        tracker = create_citation_tracker(backend="mock")
    """
    if backend == "default":
        return CitationTracker(
            enable_tracking=enable_tracking,
            require_citations=require_citations,
        )
    elif backend == "mock":
        return MockCitationTracker()
    else:
        raise ValueError(f"Unsupported citation tracker backend: {backend}")


def create_citation_tracker_from_config(settings: Settings | None = None) -> CitationTrackerProtocol:
    """
    Create CitationTracker from environment configuration.

    Reads from environment variables:
    - CEMAF_CITATION_BACKEND: Tracker backend (default: "default")
    - CEMAF_CITATION_ENABLE_TRACKING: Enable tracking (default: True)
    - CEMAF_CITATION_REQUIRE_CITATIONS: Require citations (default: False)
    - CEMAF_CITATION_CITATION_FORMAT: Format (apa, mla, chicago, ieee) (default: "apa")

    Returns:
        Configured CitationTracker instance

    Example:
        # From environment
        tracker = create_citation_tracker_from_config()
    """
    backend = os.getenv("CEMAF_CITATION_BACKEND", "default")
    enable_tracking = os.getenv("CEMAF_CITATION_ENABLE_TRACKING", "true").lower() == "true"
    require_citations = os.getenv("CEMAF_CITATION_REQUIRE_CITATIONS", "false").lower() == "true"

    # BUILT-IN IMPLEMENTATIONS
    if backend in ("default", "mock"):
        return create_citation_tracker(
            backend=backend,
            enable_tracking=enable_tracking,
            require_citations=require_citations,
        )

    # ============================================================================
    # EXTEND HERE: Bring Your Own Citation Tracker
    # ============================================================================
    # This is the extension point for custom citation tracker backends.
    #
    # To add your own implementation:
    # 1. Implement the CitationTracker protocol (see cemaf.citation.protocols)
    # 2. Add your backend case below
    # 3. Read configuration from environment variables
    #
    # Example (Database-backed):
    #   elif backend == "database":
    #       from your_package import DatabaseCitationTracker
    #
    #       db_url = os.getenv("DATABASE_URL")
    #       return DatabaseCitationTracker(
    #           connection_string=db_url,
    #           enable_tracking=enable_tracking,
    #       )
    #
    # Example (External service):
    #   elif backend == "service":
    #       from your_package import ServiceCitationTracker
    #
    #       api_url = os.getenv("CITATION_SERVICE_URL")
    #       api_key = os.getenv("CITATION_SERVICE_API_KEY")
    #       return ServiceCitationTracker(url=api_url, api_key=api_key)
    # ============================================================================

    raise ValueError(
        f"Unsupported citation tracker backend: {backend}. "
        f"Supported: default, mock. "
        f"To add your own, extend create_citation_tracker_from_config() "
        f"in cemaf/citation/factories.py"
    )
