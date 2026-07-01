"""
Factory functions for citation tracking components.

Provides convenient ways to create citation trackers with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    Register custom citation tracker backends with citation_tracker_registry.register(...).
"""

import os
from typing import Any

from cemaf.citation.mock import MockCitationTracker
from cemaf.citation.protocols import CitationTracker as CitationTrackerProtocol
from cemaf.citation.tracker import CitationTracker
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.events.protocols import EventBus

citation_tracker_registry: ProviderRegistry[CitationTrackerProtocol] = ProviderRegistry(
    name="citation_tracker"
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() == "true"


def _create_default_citation_tracker(**kwargs: Any) -> CitationTrackerProtocol:
    return CitationTracker(event_bus=kwargs.get("event_bus"))  # type: ignore[return-value]


def _create_mock_citation_tracker(**kwargs: Any) -> CitationTrackerProtocol:
    return MockCitationTracker()  # type: ignore[return-value]


citation_tracker_registry.register(backend="default", factory=_create_default_citation_tracker)
citation_tracker_registry.register(backend="mock", factory=_create_mock_citation_tracker)


def create_citation_tracker(
    backend: str = "default",
    enable_tracking: bool = True,
    require_citations: bool = False,
    citation_format: str = "apa",
    enable_validation: bool = True,
    event_bus: EventBus | None = None,
    **backend_options: Any,
) -> CitationTrackerProtocol:
    """
    Factory for CitationTracker with sensible defaults.

    Args:
        backend: Tracker backend (default, mock)
        enable_tracking: Enable citation tracking
        require_citations: Require citations for all claims
        citation_format: Citation style requested by configuration
        enable_validation: Enable citation validation
        event_bus: Optional event bus for citation events

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
    return citation_tracker_registry.create(
        backend=backend,
        enable_tracking=enable_tracking,
        require_citations=require_citations,
        citation_format=citation_format,
        enable_validation=enable_validation,
        event_bus=event_bus,
        **backend_options,
    )


def create_citation_tracker_from_config(
    settings: Settings | None = None,
    *,
    event_bus: EventBus | None = None,
) -> CitationTrackerProtocol:
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
    enable_tracking = _env_bool(
        "CEMAF_CITATION_ENABLE_TRACKING",
        settings.citation.enable_tracking if settings else True,
    )
    require_citations = _env_bool(
        "CEMAF_CITATION_REQUIRE_CITATIONS",
        settings.citation.require_citations if settings else False,
    )
    citation_format = os.getenv(
        "CEMAF_CITATION_CITATION_FORMAT",
        settings.citation.citation_format if settings else "apa",
    )
    enable_validation = _env_bool(
        "CEMAF_CITATION_ENABLE_VALIDATION",
        settings.citation.enable_validation if settings else True,
    )

    return create_citation_tracker(
        backend=backend,
        enable_tracking=enable_tracking,
        require_citations=require_citations,
        citation_format=citation_format,
        enable_validation=enable_validation,
        event_bus=event_bus,
    )
