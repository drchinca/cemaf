"""
Generation module - Protocols for generative AI outputs.

Supports:
- Image generation (DALL-E, Stable Diffusion, Midjourney)
- Audio generation (ElevenLabs, Bark, XTTS)
- Video generation (Runway, Pika, Sora)
- Diagram/visualization generation (Mermaid, D3, Charts)
- UI/Wireframe generation (v0, Figma AI, wireframe tools)
- Code generation (Codex, Claude, structured output)

All generators follow Protocol pattern for pluggability.
"""

from cemaf.generation.protocols import (
    MediaSpec,
    MediaOutput,
    ImageSpec,
    AudioSpec,
    VideoSpec,
    DiagramSpec,
    UISpec,
    CodeSpec,
    ImageGenerator,
    AudioGenerator,
    VideoGenerator,
    DiagramGenerator,
    UIGenerator,
    CodeGenerator,
)

__all__ = [
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

