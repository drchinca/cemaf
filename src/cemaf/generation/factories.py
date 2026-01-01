"""
Factory functions for generation components.

Provides convenient ways to create media generators (image, audio, video, code, etc.)
with sensible defaults while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_X_generator_from_config()
    functions include clear "EXTEND HERE" sections where you can add
    your own generator implementations (DALL-E, Stable Diffusion, ElevenLabs, etc.).
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
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


def create_image_generator(
    provider: str = "mock",
    default_width: int = 1024,
    default_height: int = 1024,
) -> ImageGenerator:
    """
    Factory for ImageGenerator with sensible defaults.

    Args:
        provider: Image generation provider (mock, dall-e, stable-diffusion, etc.)
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
    if provider == "mock":
        return MockImageGenerator(width=default_width, height=default_height)
    else:
        raise ValueError(f"Unsupported image generator: {provider}")


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
    provider = os.getenv("CEMAF_GENERATION_IMAGE_PROVIDER", "mock")
    width = int(os.getenv("CEMAF_GENERATION_DEFAULT_IMAGE_WIDTH", "1024"))
    height = int(os.getenv("CEMAF_GENERATION_DEFAULT_IMAGE_HEIGHT", "1024"))

    if provider == "mock":
        return create_image_generator(provider, width, height)

    # ============================================================================
    # EXTEND HERE: Image Generation Providers
    # ============================================================================
    # Example (DALL-E 3):
    #   elif provider == "dall-e":
    #       from your_package import DallEImageGenerator
    #       api_key = os.getenv("OPENAI_API_KEY")
    #       model = os.getenv("DALL_E_MODEL", "dall-e-3")
    #       return DallEImageGenerator(api_key=api_key, model=model)
    #
    # Example (Stable Diffusion):
    #   elif provider == "stable-diffusion":
    #       from your_package import StableDiffusionGenerator
    #       model_id = os.getenv("SD_MODEL_ID", "stable-diffusion-xl-base-1.0")
    #       return StableDiffusionGenerator(model_id=model_id)
    # ============================================================================

    raise ValueError(
        f"Unsupported image generator: {provider}. "
        f"To add your own, extend create_image_generator_from_config()"
    )


def create_audio_generator(provider: str = "mock") -> AudioGenerator:
    """Factory for AudioGenerator."""
    if provider == "mock":
        return MockAudioGenerator()
    else:
        raise ValueError(f"Unsupported audio generator: {provider}")


def create_audio_generator_from_config(settings: Settings | None = None) -> AudioGenerator:
    """Create AudioGenerator from environment configuration."""
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    provider = os.getenv("CEMAF_GENERATION_AUDIO_PROVIDER", "mock")

    if provider == "mock":
        return create_audio_generator(provider)

    # ============================================================================
    # EXTEND HERE: Audio Generation Providers
    # ============================================================================
    # Example (ElevenLabs):
    #   elif provider == "elevenlabs":
    #       from your_package import ElevenLabsGenerator
    #       api_key = os.getenv("ELEVENLABS_API_KEY")
    #       voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    #       return ElevenLabsGenerator(api_key=api_key, voice_id=voice_id)
    # ============================================================================

    raise ValueError(f"Unsupported audio generator: {provider}")


def create_video_generator(provider: str = "mock") -> VideoGenerator:
    """Factory for VideoGenerator."""
    if provider == "mock":
        return MockVideoGenerator()
    else:
        raise ValueError(f"Unsupported video generator: {provider}")


def create_video_generator_from_config(settings: Settings | None = None) -> VideoGenerator:
    """Create VideoGenerator from environment configuration."""
    provider = os.getenv("CEMAF_GENERATION_VIDEO_PROVIDER", "mock")

    if provider == "mock":
        return create_video_generator(provider)

    # ============================================================================
    # EXTEND HERE: Video Generation Providers
    # ============================================================================
    # Example (Runway):
    #   elif provider == "runway":
    #       from your_package import RunwayGenerator
    #       api_key = os.getenv("RUNWAY_API_KEY")
    #       return RunwayGenerator(api_key=api_key)
    # ============================================================================

    raise ValueError(f"Unsupported video generator: {provider}")


def create_code_generator(provider: str = "mock") -> CodeGenerator:
    """Factory for CodeGenerator."""
    if provider == "mock":
        return MockCodeGenerator()
    else:
        raise ValueError(f"Unsupported code generator: {provider}")


def create_code_generator_from_config(settings: Settings | None = None) -> CodeGenerator:
    """Create CodeGenerator from environment configuration."""
    provider = os.getenv("CEMAF_GENERATION_CODE_PROVIDER", "mock")

    if provider == "mock":
        return create_code_generator(provider)

    # ============================================================================
    # EXTEND HERE: Code Generation Providers
    # ============================================================================
    # Example (Using LLM):
    #   elif provider == "llm":
    #       from cemaf.llm.factories import create_llm_client_from_config
    #       from your_package import LLMCodeGenerator
    #       llm = create_llm_client_from_config()
    #       return LLMCodeGenerator(llm=llm)
    # ============================================================================

    raise ValueError(f"Unsupported code generator: {provider}")


def create_diagram_generator(provider: str = "mock") -> DiagramGenerator:
    """Factory for DiagramGenerator."""
    if provider == "mock":
        return MockDiagramGenerator()
    else:
        raise ValueError(f"Unsupported diagram generator: {provider}")


def create_diagram_generator_from_config(settings: Settings | None = None) -> DiagramGenerator:
    """Create DiagramGenerator from environment configuration."""
    provider = os.getenv("CEMAF_GENERATION_DIAGRAM_PROVIDER", "mock")
    return create_diagram_generator(provider)


def create_ui_generator(provider: str = "mock") -> UIGenerator:
    """Factory for UIGenerator."""
    if provider == "mock":
        return MockUIGenerator()
    else:
        raise ValueError(f"Unsupported UI generator: {provider}")


def create_ui_generator_from_config(settings: Settings | None = None) -> UIGenerator:
    """Create UIGenerator from environment configuration."""
    provider = os.getenv("CEMAF_GENERATION_UI_PROVIDER", "mock")
    return create_ui_generator(provider)
