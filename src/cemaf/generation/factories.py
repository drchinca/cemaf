"""
Extension point factories for generation backends.

These factories provide the wiring points for concrete generator implementations.
Mock generators are included for testing. Register custom backends with the
modality-specific registries to connect to real generation services.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.generation.mock import (
    MockAudioGenerator,
    MockCodeGenerator,
    MockDiagramGenerator,
    MockImageGenerator,
    MockUIGenerator,
    MockVideoGenerator,
)
from cemaf.generation.protocols import (
    AudioGenerator,
    CodeGenerator,
    DiagramGenerator,
    ImageGenerator,
    UIGenerator,
    VideoGenerator,
)

image_generator_registry: ProviderRegistry[ImageGenerator] = ProviderRegistry(name="image_generator")
audio_generator_registry: ProviderRegistry[AudioGenerator] = ProviderRegistry(name="audio_generator")
video_generator_registry: ProviderRegistry[VideoGenerator] = ProviderRegistry(name="video_generator")
code_generator_registry: ProviderRegistry[CodeGenerator] = ProviderRegistry(name="code_generator")
diagram_generator_registry: ProviderRegistry[DiagramGenerator] = ProviderRegistry(name="diagram_generator")
ui_generator_registry: ProviderRegistry[UIGenerator] = ProviderRegistry(name="ui_generator")


@dataclass(frozen=True)
class ProviderResolution:
    """Resolved provider name plus warnings gathered during fallback attempts."""

    provider: str
    warnings: tuple[str, ...] = ()


def resolve_available_provider[T](
    *,
    requested_provider: str,
    candidate_order: tuple[str, ...],
    load_provider: Callable[[str], T],
    unavailable_error: type[Exception] | tuple[type[Exception], ...] = Exception,
    preflight_check: Callable[[str], str | None] | None = None,
) -> ProviderResolution:
    """Resolve the first available provider from a candidate list.

    Explicit provider requests are returned unchanged. For ``auto`` selection,
    each candidate is preflight-checked and loaded in order; failures are
    accumulated as warnings and the first viable provider wins.
    """
    if requested_provider != "auto":
        return ProviderResolution(provider=requested_provider)

    warnings: list[str] = []
    for candidate in candidate_order:
        if preflight_check is not None:
            warning = preflight_check(candidate)
            if warning:
                warnings.append(warning)
                continue
        try:
            load_provider(candidate)
            return ProviderResolution(provider=candidate, warnings=tuple(warnings))
        except unavailable_error as exc:
            warnings.append(str(exc))

    return ProviderResolution(provider=candidate_order[0], warnings=tuple(warnings))


def _create_mock_image_generator(**kwargs: Any) -> ImageGenerator:
    return MockImageGenerator()


def _create_mock_audio_generator(**kwargs: Any) -> AudioGenerator:
    return MockAudioGenerator()


def _create_mock_video_generator(**kwargs: Any) -> VideoGenerator:
    return MockVideoGenerator()


def _create_mock_code_generator(**kwargs: Any) -> CodeGenerator:
    return MockCodeGenerator()


def _create_mock_diagram_generator(**kwargs: Any) -> DiagramGenerator:
    return MockDiagramGenerator()


def _create_mock_ui_generator(**kwargs: Any) -> UIGenerator:
    return MockUIGenerator()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() == "true"


image_generator_registry.register(backend="mock", factory=_create_mock_image_generator)
audio_generator_registry.register(backend="mock", factory=_create_mock_audio_generator)
video_generator_registry.register(backend="mock", factory=_create_mock_video_generator)
code_generator_registry.register(backend="mock", factory=_create_mock_code_generator)
diagram_generator_registry.register(backend="mock", factory=_create_mock_diagram_generator)
ui_generator_registry.register(backend="mock", factory=_create_mock_ui_generator)


def create_image_generator(
    provider: str = "mock",
    default_width: int = 1024,
    default_height: int = 1024,
    **provider_options: Any,
) -> ImageGenerator:
    """
    Factory for ImageGenerator with sensible defaults.

    Args:
        provider: Image generation provider (mock or registered custom backend)
        default_width: Default image width
        default_height: Default image height

    Returns:
        Configured ImageGenerator instance

    Example:
        # Mock generator
        generator = create_image_generator()

        # Custom dimensions
        generator = create_image_generator(default_width=512, default_height=512)
    """
    return image_generator_registry.create(
        backend=provider,
        default_width=default_width,
        default_height=default_height,
        **provider_options,
    )


def create_image_generator_from_config(settings: Settings | None = None) -> ImageGenerator:
    """
    Create ImageGenerator from environment configuration.

    Reads from environment variables:
    - CEMAF_GENERATION_IMAGE_PROVIDER: Provider (default: "mock")
    - CEMAF_GENERATION_DEFAULT_IMAGE_WIDTH: Width (default: 1024)
    - CEMAF_GENERATION_DEFAULT_IMAGE_HEIGHT: Height (default: 1024)

    Returns:
        Configured ImageGenerator instance
    """
    cfg = settings or load_settings_from_env_sync()
    generation = cfg.generation

    provider = os.getenv("CEMAF_GENERATION_IMAGE_PROVIDER", "mock")
    width = int(os.getenv("CEMAF_GENERATION_DEFAULT_IMAGE_WIDTH", str(generation.default_image_width)))
    height = int(os.getenv("CEMAF_GENERATION_DEFAULT_IMAGE_HEIGHT", str(generation.default_image_height)))
    image_format = os.getenv(
        "CEMAF_GENERATION_DEFAULT_IMAGE_FORMAT",
        generation.default_image_format,
    )

    return create_image_generator(
        provider,
        width,
        height,
        default_format=image_format,
    )


def create_audio_generator(provider: str = "mock", **provider_options: Any) -> AudioGenerator:
    """Factory for AudioGenerator."""
    return audio_generator_registry.create(backend=provider, **provider_options)


def create_audio_generator_from_config(settings: Settings | None = None) -> AudioGenerator:
    """Create AudioGenerator from environment configuration."""
    cfg = settings or load_settings_from_env_sync()
    generation = cfg.generation

    provider = os.getenv("CEMAF_GENERATION_AUDIO_PROVIDER", "mock")
    audio_format = os.getenv(
        "CEMAF_GENERATION_DEFAULT_AUDIO_FORMAT",
        generation.default_audio_format,
    )
    sample_rate = int(
        os.getenv(
            "CEMAF_GENERATION_DEFAULT_SAMPLE_RATE",
            str(generation.default_sample_rate),
        )
    )

    return create_audio_generator(
        provider,
        default_format=audio_format,
        default_sample_rate=sample_rate,
    )


def create_video_generator(provider: str = "mock", **provider_options: Any) -> VideoGenerator:
    """Factory for VideoGenerator."""
    return video_generator_registry.create(backend=provider, **provider_options)


def create_video_generator_from_config(settings: Settings | None = None) -> VideoGenerator:
    """Create VideoGenerator from environment configuration."""
    cfg = settings or load_settings_from_env_sync()
    generation = cfg.generation

    provider = os.getenv("CEMAF_GENERATION_VIDEO_PROVIDER", "mock")
    width = int(os.getenv("CEMAF_GENERATION_DEFAULT_VIDEO_WIDTH", str(generation.default_video_width)))
    height = int(os.getenv("CEMAF_GENERATION_DEFAULT_VIDEO_HEIGHT", str(generation.default_video_height)))
    fps = int(os.getenv("CEMAF_GENERATION_DEFAULT_VIDEO_FPS", str(generation.default_video_fps)))
    video_format = os.getenv(
        "CEMAF_GENERATION_DEFAULT_VIDEO_FORMAT",
        generation.default_video_format,
    )

    return create_video_generator(
        provider,
        default_width=width,
        default_height=height,
        default_fps=fps,
        default_format=video_format,
    )


def create_code_generator(provider: str = "mock", **provider_options: Any) -> CodeGenerator:
    """Factory for CodeGenerator."""
    return code_generator_registry.create(backend=provider, **provider_options)


def create_code_generator_from_config(settings: Settings | None = None) -> CodeGenerator:
    """Create CodeGenerator from environment configuration."""
    cfg = settings or load_settings_from_env_sync()
    generation = cfg.generation

    provider = os.getenv("CEMAF_GENERATION_CODE_PROVIDER", "mock")
    language = os.getenv(
        "CEMAF_GENERATION_DEFAULT_CODE_LANGUAGE",
        generation.default_code_language,
    )
    include_tests = _env_bool("CEMAF_GENERATION_INCLUDE_TESTS", generation.include_tests)
    include_docs = _env_bool("CEMAF_GENERATION_INCLUDE_DOCS", generation.include_docs)

    return create_code_generator(
        provider,
        default_language=language,
        include_tests=include_tests,
        include_docs=include_docs,
    )


def create_diagram_generator(provider: str = "mock", **provider_options: Any) -> DiagramGenerator:
    """Factory for DiagramGenerator."""
    return diagram_generator_registry.create(backend=provider, **provider_options)


def create_diagram_generator_from_config(settings: Settings | None = None) -> DiagramGenerator:
    """Create DiagramGenerator from environment configuration."""
    provider = os.getenv("CEMAF_GENERATION_DIAGRAM_PROVIDER", "mock")
    return create_diagram_generator(provider)


def create_ui_generator(provider: str = "mock", **provider_options: Any) -> UIGenerator:
    """Factory for UIGenerator."""
    return ui_generator_registry.create(backend=provider, **provider_options)


def create_ui_generator_from_config(settings: Settings | None = None) -> UIGenerator:
    """Create UIGenerator from environment configuration."""
    provider = os.getenv("CEMAF_GENERATION_UI_PROVIDER", "mock")
    return create_ui_generator(provider)
