"""
Mock generators for testing.

These return placeholder outputs without calling external APIs.
"""

from cemaf.generation.protocols import (
    AudioSpec,
    CodeSpec,
    DiagramSpec,
    ImageSpec,
    MediaOutput,
    UISpec,
    VideoSpec,
)


class MockImageGenerator:
    """Mock image generator for testing."""

    def __init__(self, latency_ms: float = 0.0) -> None:
        self._latency = latency_ms
        self.call_count = 0
        self.last_spec: ImageSpec | None = None

    async def generate(self, spec: ImageSpec) -> MediaOutput:
        """Return mock image output."""
        import asyncio

        if self._latency:
            await asyncio.sleep(self._latency / 1000)

        self.call_count += 1
        self.last_spec = spec

        # Return a 1x1 PNG placeholder
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        return MediaOutput.ok(
            content=png_1x1,
            format=spec.format.value,
            model="mock-image-v1",
            metadata={"prompt": spec.prompt, "size": f"{spec.width}x{spec.height}"},
        )

    async def edit(self, image: bytes, mask: bytes | None, spec: ImageSpec) -> MediaOutput:
        """Mock image edit."""
        self.call_count += 1
        return MediaOutput.ok(
            content=image,  # Return same image
            format=spec.format.value,
            model="mock-image-v1",
            metadata={"action": "edit"},
        )

    async def variations(self, image: bytes, count: int = 4) -> list[MediaOutput]:
        """Mock variations."""
        self.call_count += 1
        return [MediaOutput.ok(content=image, model="mock-image-v1") for _ in range(count)]


class MockAudioGenerator:
    """Mock audio generator for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_spec: AudioSpec | None = None

    async def generate(self, spec: AudioSpec) -> MediaOutput:
        """Return mock audio output."""
        self.call_count += 1
        self.last_spec = spec

        # Minimal valid WAV header
        wav_header = b"RIFF\x00\x00\x00\x00WAVEfmt "

        return MediaOutput.ok(
            content=wav_header,
            format=spec.format.value,
            model="mock-tts-v1",
            metadata={"voice": spec.voice, "language": spec.language},
        )

    async def clone_voice(self, reference_audio: bytes, spec: AudioSpec) -> MediaOutput:
        """Mock voice cloning."""
        self.call_count += 1
        return MediaOutput.ok(
            content=reference_audio,
            format=spec.format.value,
            model="mock-tts-v1",
        )

    def list_voices(self) -> list[dict]:
        """List mock voices."""
        return [
            {"id": "voice_1", "name": "Professional Female", "language": "en"},
            {"id": "voice_2", "name": "Professional Male", "language": "en"},
            {"id": "voice_3", "name": "Casual Female", "language": "en"},
        ]


class MockVideoGenerator:
    """Mock video generator for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_spec: VideoSpec | None = None

    async def generate(self, spec: VideoSpec) -> MediaOutput:
        """Return mock video output."""
        self.call_count += 1
        self.last_spec = spec

        return MediaOutput.ok(
            url="https://mock-cdn.example.com/video.mp4",
            format=spec.format.value,
            model="mock-video-v1",
            metadata={
                "duration": spec.duration_seconds,
                "fps": spec.fps,
                "resolution": f"{spec.width}x{spec.height}",
            },
        )

    async def image_to_video(self, image: bytes, spec: VideoSpec) -> MediaOutput:
        """Mock image-to-video."""
        self.call_count += 1
        return MediaOutput.ok(
            url="https://mock-cdn.example.com/animated.mp4",
            format=spec.format.value,
            model="mock-video-v1",
        )

    async def extend(self, video: bytes, spec: VideoSpec) -> MediaOutput:
        """Mock video extension."""
        self.call_count += 1
        return MediaOutput.ok(
            url="https://mock-cdn.example.com/extended.mp4",
            format=spec.format.value,
            model="mock-video-v1",
        )


class MockDiagramGenerator:
    """Mock diagram generator for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_spec: DiagramSpec | None = None

    async def generate(self, spec: DiagramSpec) -> MediaOutput:
        """Return mock diagram output."""
        self.call_count += 1
        self.last_spec = spec

        # Generate mock Mermaid code
        mermaid_code = f"""graph {spec.direction}
    A[Start] --> B[Process]
    B --> C[End]

    %% Generated from: {spec.prompt[:50]}...
"""

        return MediaOutput.ok(
            content_str=mermaid_code,
            format="mermaid",
            model="mock-diagram-v1",
            metadata={"diagram_type": spec.diagram_type.value},
        )

    async def from_data(self, data: dict, spec: DiagramSpec) -> MediaOutput:
        """Generate from structured data."""
        self.call_count += 1
        return MediaOutput.ok(
            content_str="graph TD\n    A-->B",
            format="mermaid",
            model="mock-diagram-v1",
        )

    async def render_mermaid(self, mermaid_code: str, format: str = "svg") -> MediaOutput:
        """Mock Mermaid rendering."""
        self.call_count += 1

        if format == "svg":
            svg = f"<svg><text>{mermaid_code[:20]}...</text></svg>"
            return MediaOutput.ok(content_str=svg, format="svg")
        else:
            return MediaOutput.ok(content=b"PNG", format="png")


class MockUIGenerator:
    """Mock UI/wireframe generator for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_spec: UISpec | None = None

    async def generate(self, spec: UISpec) -> MediaOutput:
        """Return mock UI code."""
        self.call_count += 1
        self.last_spec = spec

        if spec.framework == "react":
            code = f"""// Generated: {spec.prompt[:30]}...
import React from 'react';

export function GeneratedComponent() {{
  return (
    <div className="p-4">
      <h1>Generated UI</h1>
      <p>Prompt: {spec.prompt[:50]}</p>
    </div>
  );
}}
"""
        elif spec.framework == "html":
            code = f"""<!-- Generated: {spec.prompt[:30]}... -->
<!DOCTYPE html>
<html>
<head><title>Generated</title></head>
<body>
  <h1>Generated UI</h1>
</body>
</html>
"""
        else:
            code = f"// {spec.framework} component for: {spec.prompt}"

        return MediaOutput.ok(
            content_str=code,
            format=spec.framework,
            model="mock-ui-v1",
            metadata={
                "component_type": spec.component_type.value,
                "design_system": spec.design_system,
            },
        )

    async def from_screenshot(self, screenshot: bytes, spec: UISpec) -> MediaOutput:
        """Mock screenshot-to-code."""
        self.call_count += 1
        return MediaOutput.ok(
            content_str="// Recreated from screenshot\nexport function Component() {}",
            format=spec.framework,
            model="mock-ui-v1",
        )

    async def iterate(self, current: str, feedback: str, spec: UISpec) -> MediaOutput:
        """Mock iteration."""
        self.call_count += 1
        return MediaOutput.ok(
            content_str=f"// Updated based on: {feedback}\n{current}",
            format=spec.framework,
            model="mock-ui-v1",
        )


class MockCodeGenerator:
    """Mock code generator for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_spec: CodeSpec | None = None

    async def generate(self, spec: CodeSpec) -> MediaOutput:
        """Return mock generated code."""
        self.call_count += 1
        self.last_spec = spec

        lang = spec.language.value

        if lang == "python":
            code = f'''"""
Generated: {spec.prompt[:40]}...
"""

def generated_function():
    """Auto-generated function."""
    pass
'''
            if spec.include_tests:
                code += '''

def test_generated_function():
    """Test for generated function."""
    assert generated_function() is None
'''
        elif lang == "typescript":
            code = f"""/**
 * Generated: {spec.prompt[:40]}...
 */

export function generatedFunction(): void {{
  // Implementation
}}
"""
        else:
            code = f"// Generated {lang} code for: {spec.prompt}"

        return MediaOutput.ok(
            content_str=code,
            format=lang,
            model="mock-code-v1",
            metadata={
                "framework": spec.framework,
                "include_tests": spec.include_tests,
            },
        )

    async def complete(self, code: str, cursor_position: int, spec: CodeSpec) -> MediaOutput:
        """Mock code completion."""
        self.call_count += 1
        completion = "  # Auto-completed\n  pass"
        return MediaOutput.ok(
            content_str=completion,
            format=spec.language.value,
            model="mock-code-v1",
        )

    async def refactor(self, code: str, instruction: str, spec: CodeSpec) -> MediaOutput:
        """Mock refactoring."""
        self.call_count += 1
        return MediaOutput.ok(
            content_str=f"# Refactored: {instruction}\n{code}",
            format=spec.language.value,
            model="mock-code-v1",
        )

    async def explain(self, code: str, spec: CodeSpec) -> MediaOutput:
        """Mock code explanation."""
        self.call_count += 1
        return MediaOutput.ok(
            content_str=f"This code defines a function that...\n\nCode:\n{code[:100]}",
            format="markdown",
            model="mock-code-v1",
        )

    async def review(self, code: str, spec: CodeSpec) -> MediaOutput:
        """Mock code review."""
        self.call_count += 1
        return MediaOutput.ok(
            content_str="## Code Review\n\n- Consider adding type hints\n- Add docstrings",
            format="markdown",
            model="mock-code-v1",
        )
