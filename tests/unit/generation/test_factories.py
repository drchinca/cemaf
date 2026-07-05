"""Tests for generation factory helpers."""

from __future__ import annotations

import pytest

from cemaf.config.protocols import GenerationSettings, Settings
from cemaf.generation.factories import (
    ProviderResolution,
    audio_generator_registry,
    code_generator_registry,
    create_audio_generator,
    create_audio_generator_from_config,
    create_code_generator_from_config,
    create_diagram_generator_from_config,
    create_image_generator,
    create_image_generator_from_config,
    create_ui_generator_from_config,
    create_video_generator,
    create_video_generator_from_config,
    diagram_generator_registry,
    image_generator_registry,
    resolve_available_provider,
    ui_generator_registry,
    video_generator_registry,
)


def test_generation_registries_have_mock_builtin() -> None:
    registries = (
        image_generator_registry,
        audio_generator_registry,
        video_generator_registry,
        code_generator_registry,
        diagram_generator_registry,
        ui_generator_registry,
    )

    for registry in registries:
        assert registry.has(backend="mock")


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
        "default_format": "png",
    }


def test_generation_from_config_uses_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, dict[str, object]] = {}
    generator = object()

    for name in (
        "CEMAF_GENERATION_DEFAULT_IMAGE_WIDTH",
        "CEMAF_GENERATION_DEFAULT_IMAGE_HEIGHT",
        "CEMAF_GENERATION_DEFAULT_IMAGE_FORMAT",
        "CEMAF_GENERATION_DEFAULT_AUDIO_FORMAT",
        "CEMAF_GENERATION_DEFAULT_SAMPLE_RATE",
        "CEMAF_GENERATION_DEFAULT_VIDEO_WIDTH",
        "CEMAF_GENERATION_DEFAULT_VIDEO_HEIGHT",
        "CEMAF_GENERATION_DEFAULT_VIDEO_FPS",
        "CEMAF_GENERATION_DEFAULT_VIDEO_FORMAT",
        "CEMAF_GENERATION_DEFAULT_CODE_LANGUAGE",
        "CEMAF_GENERATION_INCLUDE_TESTS",
        "CEMAF_GENERATION_INCLUDE_DOCS",
    ):
        monkeypatch.delenv(name, raising=False)

    def _factory(name: str):
        def _inner(**kwargs):
            created[name] = dict(kwargs)
            return generator

        return _inner

    image_generator_registry.register(backend="settings-image", factory=_factory("image"))
    audio_generator_registry.register(backend="settings-audio", factory=_factory("audio"))
    video_generator_registry.register(backend="settings-video", factory=_factory("video"))
    code_generator_registry.register(backend="settings-code", factory=_factory("code"))

    monkeypatch.setenv("CEMAF_GENERATION_IMAGE_PROVIDER", "settings-image")
    monkeypatch.setenv("CEMAF_GENERATION_AUDIO_PROVIDER", "settings-audio")
    monkeypatch.setenv("CEMAF_GENERATION_VIDEO_PROVIDER", "settings-video")
    monkeypatch.setenv("CEMAF_GENERATION_CODE_PROVIDER", "settings-code")

    settings = Settings(
        generation=GenerationSettings(
            default_image_width=320,
            default_image_height=200,
            default_image_format="webp",
            default_audio_format="wav",
            default_sample_rate=22050,
            default_video_width=640,
            default_video_height=360,
            default_video_fps=12,
            default_video_format="webm",
            default_code_language="typescript",
            include_tests=True,
            include_docs=False,
        )
    )

    assert create_image_generator_from_config(settings=settings) is generator
    assert create_audio_generator_from_config(settings=settings) is generator
    assert create_video_generator_from_config(settings=settings) is generator
    assert create_code_generator_from_config(settings=settings) is generator

    assert created["image"] == {
        "default_width": 320,
        "default_height": 200,
        "default_format": "webp",
    }
    assert created["audio"] == {
        "default_format": "wav",
        "default_sample_rate": 22050,
    }
    assert created["video"] == {
        "default_width": 640,
        "default_height": 360,
        "default_fps": 12,
        "default_format": "webm",
    }
    assert created["code"] == {
        "default_language": "typescript",
        "include_tests": True,
        "include_docs": False,
    }


def test_all_generation_provider_env_vars_use_registered_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, str] = {}
    generator = object()

    def _factory(name: str):
        def _inner(**kwargs):
            created[name] = "created"
            return generator

        return _inner

    image_generator_registry.register(backend="env-image", factory=_factory("image"))
    audio_generator_registry.register(backend="env-audio", factory=_factory("audio"))
    video_generator_registry.register(backend="env-video", factory=_factory("video"))
    code_generator_registry.register(backend="env-code", factory=_factory("code"))
    diagram_generator_registry.register(backend="env-diagram", factory=_factory("diagram"))
    ui_generator_registry.register(backend="env-ui", factory=_factory("ui"))

    monkeypatch.setenv("CEMAF_GENERATION_IMAGE_PROVIDER", "env-image")
    monkeypatch.setenv("CEMAF_GENERATION_AUDIO_PROVIDER", "env-audio")
    monkeypatch.setenv("CEMAF_GENERATION_VIDEO_PROVIDER", "env-video")
    monkeypatch.setenv("CEMAF_GENERATION_CODE_PROVIDER", "env-code")
    monkeypatch.setenv("CEMAF_GENERATION_DIAGRAM_PROVIDER", "env-diagram")
    monkeypatch.setenv("CEMAF_GENERATION_UI_PROVIDER", "env-ui")

    assert create_image_generator_from_config() is generator
    assert create_audio_generator_from_config() is generator
    assert create_video_generator_from_config() is generator
    assert create_code_generator_from_config() is generator
    assert create_diagram_generator_from_config() is generator
    assert create_ui_generator_from_config() is generator
    assert created == {
        "image": "created",
        "audio": "created",
        "video": "created",
        "code": "created",
        "diagram": "created",
        "ui": "created",
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
