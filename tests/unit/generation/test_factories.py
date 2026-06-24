"""Tests for generation factory helpers."""

from __future__ import annotations

import pytest

from cemaf.generation.factories import ProviderResolution, resolve_available_provider


def test_resolve_available_provider_returns_explicit_provider_without_loading() -> None:
    resolution = resolve_available_provider(
        requested_provider="openai",
        candidate_order=("openai", "gemini"),
        load_provider=lambda _: pytest.fail("loader should not run for explicit providers"),
    )

    assert resolution == ProviderResolution(provider="openai")


def test_resolve_available_provider_uses_first_available_candidate() -> None:
    seen: list[str] = []

    def _load(candidate: str) -> object:
        seen.append(candidate)
        if candidate == "openai":
            raise RuntimeError("[openai] unavailable")
        return object()

    resolution = resolve_available_provider(
        requested_provider="auto",
        candidate_order=("openai", "gemini"),
        load_provider=_load,
        unavailable_error=RuntimeError,
    )

    assert seen == ["openai", "gemini"]
    assert resolution == ProviderResolution(
        provider="gemini",
        warnings=("[openai] unavailable",),
    )


def test_resolve_available_provider_respects_preflight_check() -> None:
    seen: list[str] = []

    def _load(candidate: str) -> object:
        seen.append(candidate)
        return object()

    resolution = resolve_available_provider(
        requested_provider="auto",
        candidate_order=("storyboard", "heygen"),
        load_provider=_load,
        preflight_check=lambda candidate: (
            "[storyboard] ffmpeg not found in PATH" if candidate == "storyboard" else None
        ),
    )

    assert seen == ["heygen"]
    assert resolution == ProviderResolution(
        provider="heygen",
        warnings=("[storyboard] ffmpeg not found in PATH",),
    )
