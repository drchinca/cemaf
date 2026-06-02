"""Typed value objects for external model catalogs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cemaf.core.types import JSON


@dataclass(frozen=True, slots=True)
class ModelCatalogQuery:
    """Filters and pagination options for model discovery."""

    search: str | None = None
    author: str | None = None
    task: str | tuple[str, ...] | None = None
    library: str | tuple[str, ...] | None = None
    tags: tuple[str, ...] = ()
    inference_provider: str | None = None
    sort: str | None = None
    limit: int = 25
    fetch_config: bool = False
    card_data: bool = False


@dataclass(frozen=True, slots=True)
class CatalogModel:
    """Normalized model metadata returned by catalog adapters."""

    id: str
    author: str | None = None
    task: str | None = None
    library_name: str | None = None
    tags: tuple[str, ...] = ()
    downloads: int | None = None
    likes: int | None = None
    last_modified: datetime | None = None
    gated: bool | str | None = None
    private: bool = False
    disabled: bool | None = None
    inference_provider: str | None = None
    card_data: JSON = field(default_factory=dict)
    config: JSON = field(default_factory=dict)
    raw: JSON = field(default_factory=dict)
