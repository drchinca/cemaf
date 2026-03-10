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
    # Generators
    "ImageGenerator",
    "AudioGenerator",
    "VideoGenerator",
    "DiagramGenerator",
    "UIGenerator",
    "CodeGenerator",
]
