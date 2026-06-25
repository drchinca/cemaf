"""Tests for the Hugging Face model catalog integration."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cemaf.catalog.models import ModelCatalogQuery
from cemaf.config.protocols import CatalogSettings, Settings


@pytest.fixture
def fake_hf_module() -> ModuleType:
    module = ModuleType("huggingface_hub")
    module.HfApi = MagicMock(name="HfApi")
    return module


class TestImportError:
    def test_missing_package_raises_helpful_error(self) -> None:
        sys.modules.pop("cemaf.catalog.huggingface", None)
        with (
            patch.dict("sys.modules", {"huggingface_hub": None}),
            pytest.raises(ImportError, match="huggingface_hub"),
        ):
            from cemaf.catalog.huggingface import HuggingFaceModelCatalog

            HuggingFaceModelCatalog()


class TestCatalogAdapter:
    @pytest.mark.asyncio()
    async def test_list_models_normalizes_results(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.catalog.huggingface", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.catalog.huggingface import HuggingFaceModelCatalog

            api_instance = MagicMock()
            api_instance.list_models.return_value = [
                SimpleNamespace(
                    modelId="Qwen/Qwen2.5-7B-Instruct",
                    author="Qwen",
                    pipeline_tag="text-generation",
                    tags=["transformers", "safetensors"],
                    downloads=1234,
                    likes=99,
                    lastModified="2026-05-01T12:34:56Z",
                    gated="auto",
                    private=False,
                    disabled=False,
                    cardData={"library_name": "transformers"},
                    config={"architectures": ["QwenForCausalLM"]},
                )
            ]
            fake_hf_module.HfApi.return_value = api_instance

            catalog = HuggingFaceModelCatalog(token="hf-test", default_limit=7)
            models = await catalog.list_models(
                ModelCatalogQuery(
                    search="qwen",
                    author="Qwen",
                    task="text-generation",
                    library="transformers",
                    tags=("safetensors",),
                    inference_provider="cerebras",
                    limit=5,
                    fetch_config=True,
                    card_data=True,
                )
            )

        fake_hf_module.HfApi.assert_called_once_with(
            endpoint="https://huggingface.co",
            token="hf-test",
        )
        api_instance.list_models.assert_called_once()
        kwargs = api_instance.list_models.call_args.kwargs
        assert kwargs["search"] == "qwen"
        assert kwargs["author"] == "Qwen"
        assert kwargs["inference_provider"] == "cerebras"
        assert kwargs["limit"] == 5
        assert kwargs["filter"] == ("text-generation", "transformers", "safetensors")
        assert kwargs["cardData"] is True
        assert kwargs["fetch_config"] is True

        assert len(models) == 1
        model = models[0]
        assert model.id == "Qwen/Qwen2.5-7B-Instruct"
        assert model.task == "text-generation"
        assert model.library_name == "transformers"
        assert model.tags == ("transformers", "safetensors")
        assert model.downloads == 1234
        assert model.likes == 99
        assert model.last_modified is not None
        assert model.config["architectures"] == ["QwenForCausalLM"]
        assert model.raw["author"] == "Qwen"

    @pytest.mark.asyncio()
    async def test_get_model_returns_none_on_lookup_error(self, fake_hf_module: ModuleType) -> None:
        sys.modules.pop("cemaf.catalog.huggingface", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.catalog.huggingface import HuggingFaceModelCatalog

            api_instance = MagicMock()
            api_instance.model_info.side_effect = RuntimeError("missing")
            fake_hf_module.HfApi.return_value = api_instance

            catalog = HuggingFaceModelCatalog(token="hf-test")
            model = await catalog.get_model("does/not-exist")

        assert model is None


class TestFactories:
    def test_create_model_catalog_from_config_uses_catalog_settings(
        self,
        fake_hf_module: ModuleType,
    ) -> None:
        sys.modules.pop("cemaf.catalog.huggingface", None)

        with patch.dict("sys.modules", {"huggingface_hub": fake_hf_module}):
            from cemaf.catalog.factories import create_model_catalog_from_config
            from cemaf.catalog.huggingface import HuggingFaceModelCatalog

            fake_hf_module.HfApi.return_value = MagicMock()
            settings = Settings(
                catalog=CatalogSettings(
                    backend="huggingface",
                    endpoint="https://hf.internal",
                    api_key="hf-config",
                    timeout_seconds=12.0,
                    default_limit=11,
                )
            )

            catalog = create_model_catalog_from_config(settings=settings)

        assert isinstance(catalog, HuggingFaceModelCatalog)
        fake_hf_module.HfApi.assert_called_once_with(
            endpoint="https://hf.internal",
            token="hf-config",
        )

    def test_create_model_catalog_from_config_supports_custom_env_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from cemaf.catalog.factories import catalog_registry, create_model_catalog_from_config

        class CustomCatalog:
            async def list_models(self, query=None):  # noqa: ANN001
                return ()

            async def get_model(self, model_id: str, *, revision: str | None = None):  # noqa: ANN201
                return None

        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return CustomCatalog()

        catalog_registry.register(backend="custom-env-catalog", factory=_factory)
        monkeypatch.setenv("CEMAF_CATALOG_BACKEND", "custom-env-catalog")
        monkeypatch.setenv("CEMAF_CATALOG_API_KEY", "catalog-token")
        monkeypatch.setenv("CEMAF_CATALOG_ENDPOINT", "https://catalog.internal")
        monkeypatch.setenv("CEMAF_CATALOG_TIMEOUT_SECONDS", "9.5")
        monkeypatch.setenv("CEMAF_CATALOG_DEFAULT_LIMIT", "17")

        catalog = create_model_catalog_from_config()

        assert isinstance(catalog, CustomCatalog)
        assert created["args"] == {
            "token": "catalog-token",
            "endpoint": "https://catalog.internal",
            "timeout_seconds": 9.5,
            "default_limit": 17,
        }
