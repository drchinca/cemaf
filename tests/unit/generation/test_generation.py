"""
Tests for generation module.

Tests protocols, specs, and mock implementations.
"""

import pytest

from cemaf.generation.mock import (
    MockAudioGenerator,
    MockCodeGenerator,
    MockDiagramGenerator,
    MockImageGenerator,
    MockUIGenerator,
    MockVideoGenerator,
)
from cemaf.generation.protocols import (
    AudioSpec,
    CodeLanguage,
    CodeSpec,
    DiagramSpec,
    DiagramType,
    ImageFormat,
    ImageSpec,
    MediaOutput,
    UIComponentType,
    UISpec,
    VideoSpec,
)


class TestMediaOutput:
    """Tests for MediaOutput."""

    def test_ok_with_content(self):
        """Create successful output with binary content."""
        output = MediaOutput.ok(content=b"binary", format="png")

        assert output.success
        assert output.content == b"binary"
        assert output.format == "png"

    def test_ok_with_string(self):
        """Create successful output with string content."""
        output = MediaOutput.ok(content_str="code here", format="python")

        assert output.success
        assert output.content_str == "code here"

    def test_ok_with_url(self):
        """Create successful output with URL."""
        output = MediaOutput.ok(url="https://cdn.example.com/file.mp4")

        assert output.success
        assert output.url == "https://cdn.example.com/file.mp4"

    def test_fail(self):
        """Create failed output."""
        output = MediaOutput.fail("Generation failed: timeout")

        assert not output.success
        assert "timeout" in output.error


class TestImageSpec:
    """Tests for ImageSpec."""

    def test_default_spec(self):
        """Default spec has sensible values."""
        spec = ImageSpec(prompt="A cat")

        assert spec.prompt == "A cat"
        assert spec.width == 1024
        assert spec.height == 1024
        assert spec.format == ImageFormat.PNG

    def test_custom_spec(self):
        """Custom spec preserves values."""
        spec = ImageSpec(
            prompt="Landscape",
            width=1920,
            height=1080,
            format=ImageFormat.JPEG,
            style="photorealistic",
            seed=42,
        )

        assert spec.width == 1920
        assert spec.height == 1080
        assert spec.format == ImageFormat.JPEG
        assert spec.seed == 42

    def test_spec_is_frozen(self):
        """Spec is immutable."""
        spec = ImageSpec(prompt="Test")

        with pytest.raises(Exception):  # ValidationError or TypeError
            spec.prompt = "Modified"


class TestAudioSpec:
    """Tests for AudioSpec."""

    def test_tts_spec(self):
        """TTS specification."""
        spec = AudioSpec(
            prompt="Hello world",
            voice="professional_female",
            language="en",
            speed=1.0,
        )

        assert spec.voice == "professional_female"
        assert spec.language == "en"

    def test_music_spec(self):
        """Music generation specification."""
        spec = AudioSpec(
            prompt="Upbeat electronic music",
            genre="electronic",
            tempo_bpm=128,
            duration_seconds=30.0,
        )

        assert spec.genre == "electronic"
        assert spec.tempo_bpm == 128


class TestVideoSpec:
    """Tests for VideoSpec."""

    def test_default_video_spec(self):
        """Default video spec."""
        spec = VideoSpec(prompt="A sunrise timelapse")

        assert spec.width == 1920
        assert spec.height == 1080
        assert spec.fps == 24
        assert spec.duration_seconds == 5.0

    def test_video_with_motion(self):
        """Video with camera motion."""
        spec = VideoSpec(
            prompt="Forest scene",
            camera_motion="pan_left",
            motion_strength=0.8,
        )

        assert spec.camera_motion == "pan_left"


class TestDiagramSpec:
    """Tests for DiagramSpec."""

    def test_flowchart_spec(self):
        """Flowchart specification."""
        spec = DiagramSpec(
            prompt="User login flow",
            diagram_type=DiagramType.FLOWCHART,
            direction="LR",
        )

        assert spec.diagram_type == DiagramType.FLOWCHART
        assert spec.direction == "LR"

    def test_sequence_diagram(self):
        """Sequence diagram specification."""
        spec = DiagramSpec(
            prompt="API request flow",
            diagram_type=DiagramType.SEQUENCE,
            output_format="mermaid",
        )

        assert spec.diagram_type == DiagramType.SEQUENCE


class TestUISpec:
    """Tests for UISpec."""

    def test_wireframe_spec(self):
        """Wireframe specification."""
        spec = UISpec(
            prompt="Dashboard with sidebar",
            component_type=UIComponentType.WIREFRAME,
            framework="react",
        )

        assert spec.component_type == UIComponentType.WIREFRAME
        assert spec.framework == "react"

    def test_responsive_spec(self):
        """Responsive design specification."""
        spec = UISpec(
            prompt="Mobile-first landing page",
            viewport="responsive",
            design_system="tailwind",
        )

        assert spec.viewport == "responsive"
        assert spec.design_system == "tailwind"


class TestCodeSpec:
    """Tests for CodeSpec."""

    def test_python_spec(self):
        """Python code specification."""
        spec = CodeSpec(
            prompt="REST API endpoint",
            language=CodeLanguage.PYTHON,
            framework="fastapi",
            include_tests=True,
        )

        assert spec.language == CodeLanguage.PYTHON
        assert spec.framework == "fastapi"
        assert spec.include_tests

    def test_typescript_spec(self):
        """TypeScript code specification."""
        spec = CodeSpec(
            prompt="React component",
            language=CodeLanguage.TYPESCRIPT,
            include_types=True,
        )

        assert spec.language == CodeLanguage.TYPESCRIPT
        assert spec.include_types


class TestMockImageGenerator:
    """Tests for MockImageGenerator."""

    @pytest.mark.asyncio
    async def test_generate(self):
        """Generate returns valid output."""
        gen = MockImageGenerator()
        spec = ImageSpec(prompt="A cat", width=512, height=512)

        output = await gen.generate(spec)

        assert output.success
        assert output.content is not None
        assert gen.call_count == 1
        assert gen.last_spec == spec

    @pytest.mark.asyncio
    async def test_edit(self):
        """Edit returns output."""
        gen = MockImageGenerator()
        spec = ImageSpec(prompt="Add a hat")

        output = await gen.edit(b"image", None, spec)

        assert output.success

    @pytest.mark.asyncio
    async def test_variations(self):
        """Variations returns multiple outputs."""
        gen = MockImageGenerator()

        outputs = await gen.variations(b"image", count=3)

        assert len(outputs) == 3
        assert all(o.success for o in outputs)


class TestMockAudioGenerator:
    """Tests for MockAudioGenerator."""

    @pytest.mark.asyncio
    async def test_generate_tts(self):
        """Generate TTS audio."""
        gen = MockAudioGenerator()
        spec = AudioSpec(prompt="Hello world", voice="female_1")

        output = await gen.generate(spec)

        assert output.success
        assert output.content is not None

    def test_list_voices(self):
        """List available voices."""
        gen = MockAudioGenerator()

        voices = gen.list_voices()

        assert len(voices) > 0
        assert "id" in voices[0]
        assert "name" in voices[0]


class TestMockVideoGenerator:
    """Tests for MockVideoGenerator."""

    @pytest.mark.asyncio
    async def test_generate(self):
        """Generate video returns URL."""
        gen = MockVideoGenerator()
        spec = VideoSpec(prompt="Sunset timelapse", duration_seconds=5.0)

        output = await gen.generate(spec)

        assert output.success
        assert output.url is not None

    @pytest.mark.asyncio
    async def test_image_to_video(self):
        """Animate static image."""
        gen = MockVideoGenerator()
        spec = VideoSpec(prompt="Animate this")

        output = await gen.image_to_video(b"image", spec)

        assert output.success


class TestMockDiagramGenerator:
    """Tests for MockDiagramGenerator."""

    @pytest.mark.asyncio
    async def test_generate_mermaid(self):
        """Generate Mermaid diagram."""
        gen = MockDiagramGenerator()
        spec = DiagramSpec(
            prompt="User auth flow",
            diagram_type=DiagramType.FLOWCHART,
        )

        output = await gen.generate(spec)

        assert output.success
        assert output.content_str is not None
        assert "graph" in output.content_str

    @pytest.mark.asyncio
    async def test_render_mermaid(self):
        """Render Mermaid to SVG."""
        gen = MockDiagramGenerator()

        output = await gen.render_mermaid("graph TD\nA-->B", format="svg")

        assert output.success
        assert output.format == "svg"


class TestMockUIGenerator:
    """Tests for MockUIGenerator."""

    @pytest.mark.asyncio
    async def test_generate_react(self):
        """Generate React component."""
        gen = MockUIGenerator()
        spec = UISpec(prompt="Dashboard", framework="react")

        output = await gen.generate(spec)

        assert output.success
        assert "React" in output.content_str

    @pytest.mark.asyncio
    async def test_generate_html(self):
        """Generate HTML."""
        gen = MockUIGenerator()
        spec = UISpec(prompt="Landing page", framework="html")

        output = await gen.generate(spec)

        assert output.success
        assert "DOCTYPE" in output.content_str

    @pytest.mark.asyncio
    async def test_iterate(self):
        """Iterate on design."""
        gen = MockUIGenerator()
        spec = UISpec(prompt="Dashboard", framework="react")

        output = await gen.iterate("current code", "make it darker", spec)

        assert output.success
        assert "darker" in output.content_str


class TestMockCodeGenerator:
    """Tests for MockCodeGenerator."""

    @pytest.mark.asyncio
    async def test_generate_python(self):
        """Generate Python code."""
        gen = MockCodeGenerator()
        spec = CodeSpec(
            prompt="Calculate factorial",
            language=CodeLanguage.PYTHON,
        )

        output = await gen.generate(spec)

        assert output.success
        assert "def " in output.content_str

    @pytest.mark.asyncio
    async def test_generate_with_tests(self):
        """Generate code with tests."""
        gen = MockCodeGenerator()
        spec = CodeSpec(
            prompt="Add function",
            language=CodeLanguage.PYTHON,
            include_tests=True,
        )

        output = await gen.generate(spec)

        assert output.success
        assert "test_" in output.content_str

    @pytest.mark.asyncio
    async def test_refactor(self):
        """Refactor code."""
        gen = MockCodeGenerator()
        spec = CodeSpec(prompt="", language=CodeLanguage.PYTHON)

        output = await gen.refactor("old_code()", "rename to new_code", spec)

        assert output.success
        assert "Refactored" in output.content_str

    @pytest.mark.asyncio
    async def test_review(self):
        """Review code."""
        gen = MockCodeGenerator()
        spec = CodeSpec(prompt="", language=CodeLanguage.PYTHON)

        output = await gen.review("def foo(): pass", spec)

        assert output.success
        assert "Review" in output.content_str
