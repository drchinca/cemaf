"""Protocols for external model catalogs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cemaf.catalog.models import CatalogModel, ModelCatalogQuery


@runtime_checkable
class ModelCatalog(Protocol):
    """Protocol for model registries such as the Hugging Face Hub."""

    async def list_models(
        self,
        query: ModelCatalogQuery | None = None,
    ) -> tuple[CatalogModel, ...]:
        """Return catalog entries matching the supplied query."""
        ...

    async def get_model(
        self,
        model_id: str,
        *,
        revision: str | None = None,
    ) -> CatalogModel | None:
        """Return a single catalog entry by repo/model identifier."""
        ...
