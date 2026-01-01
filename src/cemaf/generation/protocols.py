"""
Generation protocols - Abstract interfaces for generative AI.

All specs are immutable (frozen) for reproducibility.
All generators are Protocol-based for pluggability.
"""

from abc import ABC
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.core.types import JSON

# =============================================================================
# OUTPUT FORMATS
# =============================================================================


class ImageFormat(str, Enum):
    """Supported image formats."""

    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    SVG = "svg"
    GIF = "gif"


class AudioFormat(str, Enum):
    """Supported audio formats."""

    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    FLAC = "flac"


class VideoFormat(str, Enum):
    """Supported video formats."""

    MP4 = "mp4"
    WEBM = "webm"
    MOV = "mov"
    GIF = "gif"


class DiagramType(str, Enum):
    """Types of diagrams."""

    FLOWCHART = "flowchart"
    SEQUENCE = "sequence"
    CLASS = "class"
    STATE = "state"
    ER = "er"
    GANTT = "gantt"
    PIE = "pie"
    MINDMAP = "mindmap"
    ARCHITECTURE = "architecture"
    CUSTOM = "custom"


class UIComponentType(str, Enum):
    """Types of UI outputs."""

    WIREFRAME = "wireframe"
    MOCKUP = "mockup"
    PROTOTYPE = "prototype"
    COMPONENT = "component"
    PAGE = "page"
    FLOW = "flow"


class CodeLanguage(str, Enum):
    """Supported programming languages."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    RUST = "rust"
    GO = "go"
    JAVA = "java"
    SQL = "sql"
    HTML = "html"
    CSS = "css"
    SHELL = "shell"


# =============================================================================
# BASE SPECS & OUTPUT
# =============================================================================


class MediaSpec(BaseModel, ABC):
    """
    Base specification for media generation.

    All specs inherit from this and add type-specific fields.
    """

    model_config = {"frozen": True}

    prompt: str  # Main generation prompt
    negative_prompt: str | None = None  # What to avoid
    style: str | None = None  # Style guidance (brand, artistic, etc.)
    seed: int | None = None  # For reproducibility
    metadata: JSON = Field(default_factory=dict)


class MediaOutput(BaseModel):
    """
    Result of media generation.

    Can contain raw bytes, URL, or structured data depending on type.
    """

    model_config = {"frozen": True}

    success: bool
    content: bytes | None = None  # Raw binary content
    content_str: str | None = None  # String content (code, SVG, mermaid)
    url: str | None = None  # Remote URL if hosted
    format: str | None = None  # Output format

    # Generation metadata
    model: str | None = None  # Model used
    duration_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0

    error: str | None = None
    metadata: JSON = Field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        content: bytes | None = None,
        content_str: str | None = None,
        url: str | None = None,
        format: str | None = None,
        **kwargs,
    ) -> MediaOutput:
        """Create successful output."""
        return cls(
            success=True,
            content=content,
            content_str=content_str,
            url=url,
            format=format,
            **kwargs,
        )

    @classmethod
    def fail(cls, error: str, **kwargs) -> MediaOutput:
        """Create failed output."""
        return cls(success=False, error=error, **kwargs)


# =============================================================================
# IMAGE GENERATION
# =============================================================================


class ImageSpec(MediaSpec):
    """
    Specification for image generation.

    Example:
        spec = ImageSpec(
            prompt="A serene mountain landscape at sunset",
            style="photorealistic",
            width=1024,
            height=768,
            format=ImageFormat.PNG,
        )
    """

    width: int = 1024
    height: int = 1024
    format: ImageFormat = ImageFormat.PNG
    quality: Literal["draft", "standard", "hd"] = "standard"

    # Style controls
    guidance_scale: float = 7.5  # How closely to follow prompt
    num_inference_steps: int = 50


@runtime_checkable
class ImageGenerator(Protocol):
    """
    Protocol for image generation backends.

    Implement for: DALL-E, Stable Diffusion, Midjourney, Flux, etc.
    """

    async def generate(self, spec: ImageSpec) -> MediaOutput:
        """Generate an image from spec."""
        ...

    async def edit(
        self,
        image: bytes,
        mask: bytes | None,
        spec: ImageSpec,
    ) -> MediaOutput:
        """Edit an existing image."""
        ...

    async def variations(
        self,
        image: bytes,
        count: int = 4,
    ) -> list[MediaOutput]:
        """Generate variations of an image."""
        ...


# =============================================================================
# AUDIO GENERATION
# =============================================================================


class AudioSpec(MediaSpec):
    """
    Specification for audio generation.

    Supports both TTS (text-to-speech) and music generation.

    Example:
        spec = AudioSpec(
            prompt="Welcome to our product demo",
            voice="professional_female",
            format=AudioFormat.MP3,
        )
    """

    # Voice settings (for TTS)
    voice: str | None = None  # Voice ID or name
    language: str = "en"
    speed: float = 1.0  # 0.5 to 2.0
    pitch: float = 1.0  # Pitch adjustment

    # Audio settings
    format: AudioFormat = AudioFormat.MP3
    sample_rate: int = 44100
    duration_seconds: float | None = None  # For music generation

    # Music-specific
    genre: str | None = None
    tempo_bpm: int | None = None


@runtime_checkable
class AudioGenerator(Protocol):
    """
    Protocol for audio generation backends.

    Implement for: ElevenLabs, Bark, XTTS, Suno, etc.
    """

    async def generate(self, spec: AudioSpec) -> MediaOutput:
        """Generate audio from spec (TTS or music)."""
        ...

    async def clone_voice(
        self,
        reference_audio: bytes,
        spec: AudioSpec,
    ) -> MediaOutput:
        """Generate speech using cloned voice."""
        ...

    def list_voices(self) -> list[dict]:
        """List available voices."""
        ...


# =============================================================================
# VIDEO GENERATION
# =============================================================================


class VideoSpec(MediaSpec):
    """
    Specification for video generation.

    Example:
        spec = VideoSpec(
            prompt="A timelapse of a flower blooming",
            duration_seconds=5.0,
            fps=24,
            format=VideoFormat.MP4,
        )
    """

    width: int = 1920
    height: int = 1080
    duration_seconds: float = 5.0
    fps: int = 24
    format: VideoFormat = VideoFormat.MP4

    # Optional starting image
    start_image: bytes | None = None
    end_image: bytes | None = None

    # Motion settings
    motion_strength: float = 0.5  # 0 to 1
    camera_motion: str | None = None  # "pan_left", "zoom_in", etc.


@runtime_checkable
class VideoGenerator(Protocol):
    """
    Protocol for video generation backends.

    Implement for: Runway, Pika, Sora, Kling, etc.
    """

    async def generate(self, spec: VideoSpec) -> MediaOutput:
        """Generate video from spec."""
        ...

    async def image_to_video(
        self,
        image: bytes,
        spec: VideoSpec,
    ) -> MediaOutput:
        """Animate a static image."""
        ...

    async def extend(
        self,
        video: bytes,
        spec: VideoSpec,
    ) -> MediaOutput:
        """Extend an existing video."""
        ...


# =============================================================================
# DIAGRAM GENERATION
# =============================================================================


class DiagramSpec(MediaSpec):
    """
    Specification for diagram/visualization generation.

    Can output Mermaid code, SVG, or raster images.

    Example:
        spec = DiagramSpec(
            prompt="User authentication flow with OAuth",
            diagram_type=DiagramType.SEQUENCE,
            output_format="mermaid",
        )
    """

    diagram_type: DiagramType = DiagramType.FLOWCHART
    output_format: Literal["mermaid", "svg", "png", "d3"] = "mermaid"

    # Layout
    direction: Literal["TB", "BT", "LR", "RL"] = "TB"  # Top-Bottom, etc.
    theme: str = "default"  # mermaid theme

    # Data for data-driven diagrams
    data: JSON | None = None  # For charts, ER diagrams, etc.


@runtime_checkable
class DiagramGenerator(Protocol):
    """
    Protocol for diagram generation.

    Implement for: Mermaid, D3, Chart.js, Graphviz, etc.
    """

    async def generate(self, spec: DiagramSpec) -> MediaOutput:
        """Generate diagram from spec."""
        ...

    async def from_data(
        self,
        data: JSON,
        spec: DiagramSpec,
    ) -> MediaOutput:
        """Generate data visualization from structured data."""
        ...

    async def render_mermaid(
        self,
        mermaid_code: str,
        format: Literal["svg", "png"] = "svg",
    ) -> MediaOutput:
        """Render Mermaid code to image."""
        ...


# =============================================================================
# UI / WIREFRAME GENERATION
# =============================================================================


class UISpec(MediaSpec):
    """
    Specification for UI/wireframe generation.

    Example:
        spec = UISpec(
            prompt="Dashboard for analytics app with sidebar navigation",
            component_type=UIComponentType.PAGE,
            framework="react",
            output_format="code",
        )
    """

    component_type: UIComponentType = UIComponentType.WIREFRAME

    # Target framework/format
    framework: Literal["react", "vue", "svelte", "html", "figma"] = "react"
    output_format: Literal["code", "image", "figma_json"] = "code"

    # Design system
    design_system: str | None = None  # "tailwind", "material", "shadcn", etc.
    color_scheme: Literal["light", "dark", "auto"] = "auto"

    # Layout hints
    viewport: Literal["mobile", "tablet", "desktop", "responsive"] = "responsive"

    # Reference
    reference_image: bytes | None = None  # Screenshot to recreate
    brand_guidelines: JSON | None = None


@runtime_checkable
class UIGenerator(Protocol):
    """
    Protocol for UI/wireframe generation.

    Implement for: v0.dev, Figma AI, Galileo AI, wireframe tools, etc.
    """

    async def generate(self, spec: UISpec) -> MediaOutput:
        """Generate UI component/page from spec."""
        ...

    async def from_screenshot(
        self,
        screenshot: bytes,
        spec: UISpec,
    ) -> MediaOutput:
        """Recreate UI from screenshot."""
        ...

    async def iterate(
        self,
        current: str,  # Current code/design
        feedback: str,  # What to change
        spec: UISpec,
    ) -> MediaOutput:
        """Iterate on existing UI based on feedback."""
        ...


# =============================================================================
# CODE GENERATION
# =============================================================================


class CodeSpec(MediaSpec):
    """
    Specification for code generation.

    Example:
        spec = CodeSpec(
            prompt="REST API endpoint for user registration with validation",
            language=CodeLanguage.PYTHON,
            framework="fastapi",
            include_tests=True,
        )
    """

    language: CodeLanguage = CodeLanguage.PYTHON
    framework: str | None = None  # "fastapi", "express", "rails", etc.

    # Output options
    include_tests: bool = False
    include_docs: bool = True
    include_types: bool = True

    # Context
    existing_code: str | None = None  # Code to modify/extend
    dependencies: list[str] = Field(default_factory=list)

    # Style
    style_guide: str | None = None  # "google", "pep8", "airbnb", etc.
    max_line_length: int = 100


@runtime_checkable
class CodeGenerator(Protocol):
    """
    Protocol for code generation.

    Implement for: OpenAI Codex, Claude, specialized code models, etc.
    """

    async def generate(self, spec: CodeSpec) -> MediaOutput:
        """Generate code from spec."""
        ...

    async def complete(
        self,
        code: str,
        cursor_position: int,
        spec: CodeSpec,
    ) -> MediaOutput:
        """Complete code at cursor position."""
        ...

    async def refactor(
        self,
        code: str,
        instruction: str,
        spec: CodeSpec,
    ) -> MediaOutput:
        """Refactor existing code based on instruction."""
        ...

    async def explain(
        self,
        code: str,
        spec: CodeSpec,
    ) -> MediaOutput:
        """Explain what code does."""
        ...

    async def review(
        self,
        code: str,
        spec: CodeSpec,
    ) -> MediaOutput:
        """Review code and suggest improvements."""
        ...
