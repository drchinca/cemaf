"""Factory functions for model catalog components."""

from __future__ import annotations

import os
from typing import Any

from cemaf.catalog.models import CatalogModel, ModelCatalogQuery
from cemaf.catalog.protocols import ModelCatalog
from cemaf.config.protocols import Settings
from cemaf.core.defaults import DEFAULT_FREE_CATALOG_BACKEND, DEFAULT_FREE_LLM_MODEL
from cemaf.core.provider_registry import ProviderRegistry

catalog_registry: ProviderRegistry[ModelCatalog] = ProviderRegistry(name="model_catalog")


class StaticModelCatalog:
    """Offline catalog containing CEMAF's free-first local defaults."""

    def __init__(
        self,
        *,
        models: tuple[CatalogModel, ...] | None = None,
        default_limit: int = 25,
    ) -> None:
        self._models = models or (
            CatalogModel(
                id=f"ollama:{DEFAULT_FREE_LLM_MODEL}",
                author="local",
                task="text-generation",
                library_name="ollama",
                tags=("local", "offline", "free-first"),
                inference_provider="ollama",
            ),
        )
        self._default_limit = default_limit

    async def list_models(
        self,
        query: ModelCatalogQuery | None = None,
    ) -> tuple[CatalogModel, ...]:
        resolved_query = query or ModelCatalogQuery(limit=self._default_limit)
        models = self._models
        if resolved_query.search:
            needle = resolved_query.search.lower()
            models = tuple(model for model in models if needle in model.id.lower())
        if resolved_query.author:
            models = tuple(model for model in models if model.author == resolved_query.author)
        if resolved_query.task:
            tasks = (resolved_query.task,) if isinstance(resolved_query.task, str) else resolved_query.task
            models = tuple(model for model in models if model.task in tasks)
        if resolved_query.tags:
            required = set(resolved_query.tags)
            models = tuple(model for model in models if required.issubset(set(model.tags)))
        return models[: max(1, resolved_query.limit or self._default_limit)]

    async def get_model(
        self,
        model_id: str,
        *,
        revision: str | None = None,
    ) -> CatalogModel | None:
        del revision
        normalized_ids = {model_id, model_id.removeprefix("ollama:")}
        for model in self._models:
            if model.id in normalized_ids or model.id.removeprefix("ollama:") in normalized_ids:
                return model
        return None


def _resolve_hf_token(explicit_token: str | None = None) -> str:
    return str(
        explicit_token
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_API_KEY")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN", "")
    )


def _create_huggingface_catalog(**kwargs: Any) -> ModelCatalog:
    from cemaf.catalog.huggingface import HuggingFaceModelCatalog

    return HuggingFaceModelCatalog(
        token=_resolve_hf_token(kwargs.get("token")),
        endpoint=str(kwargs.get("endpoint", "https://huggingface.co")),
        timeout_seconds=float(kwargs.get("timeout_seconds", 30.0)),
        default_limit=int(kwargs.get("default_limit", 25)),
    )


def _create_static_catalog(**kwargs: Any) -> ModelCatalog:
    return StaticModelCatalog(default_limit=int(kwargs.get("default_limit", 25)))


catalog_registry.register(backend="static", factory=_create_static_catalog)
catalog_registry.register(backend="huggingface", factory=_create_huggingface_catalog)


def create_model_catalog(
    backend: str = DEFAULT_FREE_CATALOG_BACKEND,
    **kwargs: Any,
) -> ModelCatalog:
    """Create a model catalog adapter for the requested backend."""

    return catalog_registry.create(backend=backend, **kwargs)


def create_model_catalog_from_config(
    backend: str | None = None,
    settings: Settings | None = None,
) -> ModelCatalog:
    """Create a model catalog from `Settings` configuration."""
    if settings:
        backend_name = str(backend or settings.catalog.backend)
        token = settings.catalog.api_key
        endpoint = settings.catalog.endpoint
        timeout_seconds = settings.catalog.timeout_seconds
        default_limit = settings.catalog.default_limit
    else:
        backend_name = str(backend or os.getenv("CEMAF_CATALOG_BACKEND", DEFAULT_FREE_CATALOG_BACKEND))
        token = os.getenv("CEMAF_CATALOG_API_KEY", "")
        endpoint = os.getenv("CEMAF_CATALOG_ENDPOINT", "")
        timeout_seconds = float(os.getenv("CEMAF_CATALOG_TIMEOUT_SECONDS", "30.0"))
        default_limit = int(os.getenv("CEMAF_CATALOG_DEFAULT_LIMIT", "25"))

    return catalog_registry.create(
        backend=backend_name,
        token=token,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        default_limit=default_limit,
    )
