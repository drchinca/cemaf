"""Integration test: cemaf.catalog (ModelCatalog) → cemaf.llm.model_router.ModelRouter.

Proves the "fetch a model at will, then route to it" claim is a real seam: a
catalog discovers a model id, that id is wired into a ModelRoute, and the
ModelRouter dispatches a completion to the matching client.

The catalog network boundary is faked (a protocol-conformant in-memory catalog),
but the ModelRouter and the route's LLM client are REAL — per the house rule, the
system under test is not mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cemaf.catalog import CatalogModel, ModelCatalog, ModelCatalogQuery
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.model_router import ModelRoute, ModelRouter
from cemaf.llm.protocols import LLMConfig, Message


class InMemoryCatalog:
    """Protocol-conformant ModelCatalog with no network — the discovery boundary fake."""

    def __init__(self, models: list[CatalogModel]) -> None:
        self._models = list(models)

    async def list_models(self, query: ModelCatalogQuery | None = None) -> tuple[CatalogModel, ...]:
        if query is None or query.task is None:
            return tuple(self._models)
        return tuple(m for m in self._models if m.task == query.task)

    async def get_model(self, model_id: str, *, revision: str | None = None) -> CatalogModel | None:
        return next((m for m in self._models if m.id == model_id), None)


def _model(model_id: str, task: str) -> CatalogModel:
    return CatalogModel(id=model_id, task=task, last_modified=datetime.now(tz=UTC))


def test_in_memory_catalog_satisfies_protocol() -> None:
    """The fake must structurally satisfy the ModelCatalog protocol (no drift)."""
    assert isinstance(InMemoryCatalog([]), ModelCatalog)


@pytest.mark.asyncio
async def test_catalog_discovery_feeds_router_dispatch() -> None:
    """Discover a model from the catalog → build a route from its id → router dispatches to it."""
    catalog = InMemoryCatalog(
        [
            _model("google/gemma-2-2b-it", task="text-generation"),
            _model("sentence-transformers/all-MiniLM-L6-v2", task="feature-extraction"),
        ]
    )

    # 1. Discover a model "at will" by task.
    matches = await catalog.list_models(query=ModelCatalogQuery(task="text-generation"))
    assert len(matches) == 1
    discovered = matches[0]
    assert discovered.id == "google/gemma-2-2b-it"

    # 2. Wire the discovered model id into a real ModelRoute backed by a real client.
    client = MockLLMClient(responses=["routed-to-gemma"], config=LLMConfig(model=discovered.id))
    router = ModelRouter(routes=[ModelRoute(threshold=0.0, client=client, model_name=discovered.id)])

    # 3. The router dispatches a completion to the discovered model.
    result = await router.complete(messages=[Message.user(content="hola")])

    assert result.success
    assert result.message.content == "routed-to-gemma"
    assert router.config.model == "google/gemma-2-2b-it"
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_catalog_get_model_then_route_by_complexity() -> None:
    """get_model by id → register as a tier in a multi-route router → complexity routing works."""
    catalog = InMemoryCatalog([_model("Qwen/Qwen2.5-Coder-7B", task="text-generation")])

    fetched = await catalog.get_model("Qwen/Qwen2.5-Coder-7B")
    assert fetched is not None

    # Router contract: ascending-sorted thresholds are ceilings — the first route
    # whose threshold EXCEEDS the complexity score wins. So the cheap/small tier
    # carries the lower ceiling (0.5) and the large tier the higher one (1.0).
    small = MockLLMClient(responses=["small-tier"], config=LLMConfig(model="gemma3:4b"))
    large = MockLLMClient(responses=["large-tier"], config=LLMConfig(model=fetched.id))
    router = ModelRouter(
        routes=[
            ModelRoute(threshold=0.5, client=small, model_name="gemma3:4b"),
            ModelRoute(threshold=1.0, client=large, model_name=fetched.id),
        ]
    )

    # A trivial prompt scores low complexity (~0.008) → small tier handles it.
    result = await router.complete(messages=[Message.user(content="hi")])

    assert result.success
    assert result.message.content == "small-tier"
    assert small.call_count == 1
    assert large.call_count == 0


@pytest.mark.asyncio
async def test_catalog_miss_returns_none() -> None:
    """A model not in the catalog returns None — caller must handle absence before routing."""
    catalog = InMemoryCatalog([_model("google/gemma-2-2b-it", task="text-generation")])

    assert await catalog.get_model("nonexistent/model") is None
