"""Hugging Face Hub-backed model catalog."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from cemaf.catalog.models import CatalogModel, ModelCatalogQuery


class HuggingFaceModelCatalog:
    """Discover models from the Hugging Face Hub via `huggingface_hub.HfApi`."""

    def __init__(
        self,
        *,
        token: str = "",
        endpoint: str = "https://huggingface.co",
        timeout_seconds: float = 30.0,
        default_limit: int = 25,
    ) -> None:
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub package is required for HuggingFaceModelCatalog. "
                "Install it with: uv add huggingface_hub"
            ) from exc

        self._api = HfApi(endpoint=endpoint, token=token or None)
        self._timeout_seconds = timeout_seconds
        self._default_limit = default_limit

    async def list_models(
        self,
        query: ModelCatalogQuery | None = None,
    ) -> tuple[CatalogModel, ...]:
        """List models from the Hugging Face Hub using typed query filters."""

        resolved_query = query or ModelCatalogQuery(limit=self._default_limit)
        filter_terms = _collect_filter_terms(resolved_query=resolved_query)
        limit = max(1, resolved_query.limit or self._default_limit)

        kwargs: dict[str, Any] = {
            "search": resolved_query.search,
            "author": resolved_query.author,
            "inference_provider": resolved_query.inference_provider,
            "sort": resolved_query.sort,
            "limit": limit,
            "cardData": resolved_query.card_data,
            "fetch_config": resolved_query.fetch_config,
            "full": True,
        }
        if filter_terms:
            kwargs["filter"] = tuple(filter_terms)

        models = await asyncio.wait_for(
            asyncio.to_thread(lambda: list(self._api.list_models(**kwargs))),
            timeout=self._timeout_seconds,
        )
        return tuple(_normalize_model_info(model_info) for model_info in models)

    async def get_model(
        self,
        model_id: str,
        *,
        revision: str | None = None,
    ) -> CatalogModel | None:
        """Get one model repo from the Hugging Face Hub."""

        try:
            model_info = await asyncio.wait_for(
                asyncio.to_thread(
                    self._api.model_info,
                    repo_id=model_id,
                    revision=revision,
                    securityStatus=True,
                ),
                timeout=self._timeout_seconds,
            )
        except Exception:
            return None

        return _normalize_model_info(model_info)


def _collect_filter_terms(*, resolved_query: ModelCatalogQuery) -> list[str]:
    filter_terms: list[str] = []
    filter_terms.extend(_normalize_filter_value(resolved_query.task))
    filter_terms.extend(_normalize_filter_value(resolved_query.library))
    filter_terms.extend(resolved_query.tags)
    return filter_terms


def _normalize_filter_value(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return value


def _normalize_model_info(model_info: object) -> CatalogModel:
    raw = _to_json_dict(model_info)
    card_data = _coerce_json_dict(
        getattr(model_info, "cardData", None) or getattr(model_info, "card_data", None),
    )
    config = _coerce_json_dict(getattr(model_info, "config", None))
    return CatalogModel(
        id=str(getattr(model_info, "id", None) or getattr(model_info, "modelId", "")),
        author=_coerce_optional_str(getattr(model_info, "author", None)),
        task=_coerce_optional_str(
            getattr(model_info, "pipeline_tag", None) or getattr(model_info, "pipelineTag", None),
        ),
        library_name=_coerce_optional_str(
            getattr(model_info, "library_name", None) or card_data.get("library_name"),
        ),
        tags=_coerce_tags(getattr(model_info, "tags", None)),
        downloads=_coerce_optional_int(getattr(model_info, "downloads", None)),
        likes=_coerce_optional_int(getattr(model_info, "likes", None)),
        last_modified=_coerce_optional_datetime(
            getattr(model_info, "last_modified", None) or getattr(model_info, "lastModified", None),
        ),
        gated=getattr(model_info, "gated", None),
        private=bool(getattr(model_info, "private", False)),
        disabled=_coerce_optional_bool(getattr(model_info, "disabled", None)),
        inference_provider=_coerce_optional_str(getattr(model_info, "inference_provider", None)),
        card_data=card_data,
        config=config,
        raw=raw,
    )


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _coerce_optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def _coerce_tags(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _coerce_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _coerce_json_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return {str(key): _to_json_value(item) for key, item in dumped.items()}
    if hasattr(value, "__dict__"):
        return _to_json_dict(value)
    return {"value": _to_json_value(value)}


def _to_json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}

    data = getattr(value, "__dict__", None)
    if isinstance(data, dict):
        return {str(key): _to_json_value(item) for key, item in data.items() if not str(key).startswith("_")}

    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return {str(key): _to_json_value(item) for key, item in dumped.items()}

    return {"value": _to_json_value(value)}


def _to_json_value(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_value(item) for item in value]
    if hasattr(value, "model_dump"):
        return _to_json_value(value.model_dump())
    data = getattr(value, "__dict__", None)
    if isinstance(data, dict):
        return {str(key): _to_json_value(item) for key, item in data.items() if not str(key).startswith("_")}
    return str(value)
