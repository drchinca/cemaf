"""Factory functions for model catalog components."""

from __future__ import annotations

import os
from typing import Any

from cemaf.catalog.protocols import ModelCatalog
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry

catalog_registry: ProviderRegistry[ModelCatalog] = ProviderRegistry(name="model_catalog")


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


catalog_registry.register(backend="huggingface", factory=_create_huggingface_catalog)


def create_model_catalog(
    backend: str,
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
        backend_name = str(backend or os.getenv("CEMAF_CATALOG_BACKEND", "huggingface"))
        token = os.getenv("CEMAF_CATALOG_API_KEY", "")
        endpoint = os.getenv("CEMAF_CATALOG_ENDPOINT", "https://huggingface.co")
        timeout_seconds = float(os.getenv("CEMAF_CATALOG_TIMEOUT_SECONDS", "30.0"))
        default_limit = int(os.getenv("CEMAF_CATALOG_DEFAULT_LIMIT", "25"))

    return catalog_registry.create(
        backend=backend_name,
        token=token,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        default_limit=default_limit,
    )
