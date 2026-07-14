"""Catalog module - discover models and artifacts through typed adapters.

Provides:
- ModelCatalog protocol for registry-backed discovery
- CatalogModel / ModelCatalogQuery value objects
- Static offline catalog for free-first defaults
- Hugging Face Hub catalog implementation
- Factory helpers aligned with CEMAF's provider registry pattern
"""

from cemaf.catalog.factories import (
    StaticModelCatalog,
    catalog_registry,
    create_model_catalog,
    create_model_catalog_from_config,
)
from cemaf.catalog.huggingface import HuggingFaceModelCatalog
from cemaf.catalog.models import CatalogModel, ModelCatalogQuery
from cemaf.catalog.protocols import ModelCatalog

__all__ = [
    "CatalogModel",
    "HuggingFaceModelCatalog",
    "ModelCatalog",
    "ModelCatalogQuery",
    "StaticModelCatalog",
    "catalog_registry",
    "create_model_catalog",
    "create_model_catalog_from_config",
]
