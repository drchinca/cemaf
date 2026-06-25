"""
Generation module - Protocols for generative AI outputs.

**Extension Point** — This module defines protocols and specs for content generation.
No concrete generator implementations are included beyond mocks for testing.
Implement the protocols (ImageGenerator, AudioGenerator, etc.) to connect to your
generation backends (DALL-E, Stable Diffusion, ElevenLabs, etc.).

Supported modalities:
- Image generation (DALL-E, Stable Diffusion, Midjourney)
- Audio generation (ElevenLabs, Bark, XTTS)
- Video generation (Runway, Pika, Sora)
- Diagram/visualization generation (Mermaid, D3, Charts)
- UI/Wireframe generation (v0, Figma AI, wireframe tools)
- Code generation (Codex, Claude, structured output)
"""

from cemaf.generation.factories import (
    ProviderResolution,
    audio_generator_registry,
    code_generator_registry,
    create_audio_generator,
    create_audio_generator_from_config,
    create_code_generator,
    create_code_generator_from_config,
    create_diagram_generator,
    create_diagram_generator_from_config,
    create_image_generator,
    create_image_generator_from_config,
    create_ui_generator,
    create_ui_generator_from_config,
    create_video_generator,
    create_video_generator_from_config,
    diagram_generator_registry,
    image_generator_registry,
    resolve_available_provider,
    ui_generator_registry,
    video_generator_registry,
)
from cemaf.generation.protocols import (
    AudioFormat,
    AudioGenerator,
    AudioSpec,
    CodeGenerator,
    CodeLanguage,
    CodeSpec,
    DiagramGenerator,
    DiagramSpec,
    DiagramType,
    ImageFormat,
    ImageGenerator,
    ImageSpec,
    MediaOutput,
    MediaSpec,
    UIComponentType,
    UIGenerator,
    UISpec,
    VideoFormat,
    VideoGenerator,
    VideoSpec,
)

__all__ = [
    # Enums
    "ImageFormat",
    "AudioFormat",
    "VideoFormat",
    "DiagramType",
    "UIComponentType",
    "CodeLanguage",
    # Specs
    "MediaSpec",
    "MediaOutput",
    "ImageSpec",
    "AudioSpec",
    "VideoSpec",
    "DiagramSpec",
    "UISpec",
    "CodeSpec",
    "ProviderResolution",
    # Generators
    "ImageGenerator",
    "AudioGenerator",
    "VideoGenerator",
    "DiagramGenerator",
    "UIGenerator",
    "CodeGenerator",
    # Factories
    "create_image_generator",
    "create_image_generator_from_config",
    "create_audio_generator",
    "create_audio_generator_from_config",
    "create_video_generator",
    "create_video_generator_from_config",
    "create_code_generator",
    "create_code_generator_from_config",
    "create_diagram_generator",
    "create_diagram_generator_from_config",
    "create_ui_generator",
    "create_ui_generator_from_config",
    # Registries
    "image_generator_registry",
    "audio_generator_registry",
    "video_generator_registry",
    "code_generator_registry",
    "diagram_generator_registry",
    "ui_generator_registry",
    "resolve_available_provider",
]
