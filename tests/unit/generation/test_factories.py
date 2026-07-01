"""Tests for generation factory helpers."""

from __future__ import annotations

import pytest

from cemaf.generation.factories import (
    ProviderResolution,
    audio_generator_registry,
    create_audio_generator,
    create_image_generator,
    create_image_generator_from_config,
    create_video_generator,
    image_generator_registry,
    resolve_available_provider,
    video_generator_registry,
)


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


def test_image_generator_registry_supports_custom_backend() -> None:
    created: dict[str, object] = {}
    custom_generator = object()

    def _factory(**kwargs):
        created["args"] = kwargs
        return custom_generator

    image_generator_registry.register(backend="custom-test-image", factory=_factory)

    generator = create_image_generator(
        provider="custom-test-image",
        default_width=512,
        default_height=256,
        api_key="test-key",
    )

    assert generator is custom_generator
    assert created["args"] == {
        "default_width": 512,
        "default_height": 256,
        "api_key": "test-key",
    }


def test_image_generator_from_config_uses_registered_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}
    custom_generator = object()

    def _factory(**kwargs):
        created["args"] = kwargs
        return custom_generator

    image_generator_registry.register(backend="env-test-image", factory=_factory)
    monkeypatch.setenv("CEMAF_GENERATION_IMAGE_PROVIDER", "env-test-image")
    monkeypatch.setenv("CEMAF_GENERATION_DEFAULT_IMAGE_WIDTH", "640")
    monkeypatch.setenv("CEMAF_GENERATION_DEFAULT_IMAGE_HEIGHT", "480")

    generator = create_image_generator_from_config()

    assert generator is custom_generator
    assert created["args"] == {
        "default_width": 640,
        "default_height": 480,
    }


def test_audio_and_video_registries_support_custom_backends() -> None:
    audio = object()
    video = object()

    audio_generator_registry.register(backend="custom-test-audio", factory=lambda **_: audio)
    video_generator_registry.register(backend="custom-test-video", factory=lambda **_: video)

    assert create_audio_generator("custom-test-audio") is audio
    assert create_video_generator("custom-test-video") is video


def test_generator_registry_error_mentions_registration() -> None:
    with pytest.raises(ValueError, match="image_generator_registry.register"):
        create_image_generator(provider="missing-image-provider")
