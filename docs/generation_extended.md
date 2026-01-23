# Generation Module - Extended Documentation

## Overview

The generation module provides protocols for multi-modal content generation (images, audio, video, code, diagrams, UI), enabling agents to generate diverse media types with consistent interfaces.

**What it does**: Defines generator protocols for different media types (ImageGenerator, AudioGenerator, VideoGenerator, CodeGenerator, DiagramGenerator, UIGenerator). Each protocol specifies input specs, output types, and configuration. Applications implement generators to integrate different services (DALL-E, Midjourney, Stable Diffusion, etc.).

**Key use cases**:
- Generate product images for e-commerce
- Create audio voiceovers for video content
- Generate code snippets for documentation
- Create diagrams and visualizations
- Generate UI mockups and wireframes
- Generate video storyboards
- Create presentation graphics

**When to use vs. alternatives**: Use generation when you need to create new media as part of automation. Use it for multi-media content workflows. Don't use for image manipulation (use image editing libraries), or when you have pre-existing media (use those directly).

## Core Concepts

### Multi-Modal Generation

Different media types require different generators:

**Image**: Photo-realistic, illustration, diagram generation. Specs: dimensions, style, prompt.

**Audio**: Voice synthesis, music generation. Specs: voice, language, speed, emotion.

**Video**: Short clips, animations. Specs: duration, resolution, style, script.

**Code**: Code snippets, programs. Specs: language, style, complexity, libraries.

**Diagram**: Flowcharts, charts, technical diagrams. Specs: type, data, style.

**UI**: Wireframes, mockups. Specs: framework, style, components.

### MediaOutput

All generators return MediaOutput:
- URL/path to generated media
- Metadata (resolution, duration, size, etc.)
- Usage information (tokens, cost, latency)
- Thumbnail or preview

### Generator Configuration

Generators can be configured via specs:

```python
image_spec = ImageSpec(
    prompt="A serene landscape",
    width=1024,
    height=768,
    style="oil painting",
    quality="high"
)

audio_spec = AudioSpec(
    text="Hello world",
    voice="en-US-Neural2-A",
    speaking_rate=1.0,
    language="en-US"
)
```

## Usage Examples

### Image Generation

```python
from cemaf.generation import ImageGenerator, ImageSpec

class MidjourneyGenerator(ImageGenerator):
    """Generate images using Midjourney."""

    async def generate(self, spec: ImageSpec) -> MediaOutput:
        # Build prompt
        prompt = f"{spec.prompt} --ar {spec.width}:{spec.height}"
        if spec.style:
            prompt += f" --style {spec.style}"

        # Submit to Midjourney
        job = await midjourney_api.submit(prompt)

        # Poll for completion
        for _ in range(60):  # 60 seconds
            result = await midjourney_api.get_status(job.id)
            if result.completed:
                return MediaOutput(
                    url=result.image_url,
                    metadata={
                        "width": spec.width,
                        "height": spec.height,
                        "style": spec.style,
                        "generation_time_seconds": result.duration
                    }
                )
            await asyncio.sleep(1)

        raise TimeoutError("Image generation timeout")

# Use generator
generator = MidjourneyGenerator()
spec = ImageSpec(
    prompt="A futuristic city at night",
    width=1024,
    height=768,
    style="cyberpunk"
)

output = await generator.generate(spec)
print(f"Generated image: {output.url}")
```

### Audio Generation

```python
from cemaf.generation import AudioGenerator, AudioSpec

class ElevenLabsGenerator(AudioGenerator):
    """Generate audio using ElevenLabs."""

    async def generate(self, spec: AudioSpec) -> MediaOutput:
        # Get voice ID
        voice_id = await self._get_voice_id(spec.voice)

        # Generate speech
        response = await elevenlabs_api.text_to_speech(
            text=spec.text,
            voice_id=voice_id,
            speaking_rate=spec.speaking_rate
        )

        # Save audio file
        audio_path = await self._save_audio(response.audio_data)

        return MediaOutput(
            url=audio_path,
            metadata={
                "duration_seconds": response.duration,
                "voice": spec.voice,
                "format": "mp3",
                "size_bytes": len(response.audio_data)
            }
        )

# Use generator
generator = ElevenLabsGenerator()
spec = AudioSpec(
    text="Welcome to our product",
    voice="Elena",
    speaking_rate=1.0
)

output = await generator.generate(spec)
print(f"Generated audio: {output.url} ({output.metadata['duration_seconds']}s)")
```

### Code Generation

```python
from cemaf.generation import CodeGenerator, CodeSpec

class ClaudeCodeGenerator(CodeGenerator):
    """Generate code using Claude."""

    async def generate(self, spec: CodeSpec) -> MediaOutput:
        prompt = f"""Generate {spec.language} code for:
{spec.description}

Requirements:
- Language: {spec.language}
- Style: {spec.style}
- Libraries: {', '.join(spec.libraries)}
- Complexity: {spec.complexity}

Return only the code, no explanations."""

        response = await claude_api.generate(prompt)

        # Save code file
        code_path = await self._save_code(response.text, spec.language)

        return MediaOutput(
            url=code_path,
            metadata={
                "language": spec.language,
                "lines": response.text.count('\n'),
                "tokens": response.usage.output_tokens,
                "style": spec.style
            }
        )

# Use generator
generator = ClaudeCodeGenerator()
spec = CodeSpec(
    description="API endpoint to fetch user data",
    language="python",
    style="fastapi",
    libraries=["fastapi", "sqlalchemy"],
    complexity="medium"
)

output = await generator.generate(spec)
print(f"Generated code:\n{output.url}")
```

### Composite Generation (Multi-media)

```python
# Generate multiple media types for campaign
class CampaignMediaGenerator:
    def __init__(self, image_gen, audio_gen, code_gen):
        self.image_gen = image_gen
        self.audio_gen = audio_gen
        self.code_gen = code_gen

    async def generate_campaign(self, brief: str):
        # Generate marketing image
        image_spec = ImageSpec(
            prompt=f"Marketing image for: {brief}",
            width=1200,
            height=630,
            style="modern"
        )
        image = await self.image_gen.generate(image_spec)

        # Generate voiceover
        audio_spec = AudioSpec(
            text=f"Discover the future with {brief}",
            voice="professional",
            speaking_rate=0.9
        )
        audio = await self.audio_gen.generate(audio_spec)

        # Generate landing page code
        code_spec = CodeSpec(
            description=f"Landing page for {brief}",
            language="html",
            style="tailwind",
            libraries=["tailwind-css"]
        )
        code = await self.code_gen.generate(code_spec)

        return {
            "image": image,
            "audio": audio,
            "code": code
        }
```

### Diagram Generation

```python
from cemaf.generation import DiagramGenerator, DiagramSpec

class MermaidDiagramGenerator(DiagramGenerator):
    """Generate diagrams using Mermaid."""

    async def generate(self, spec: DiagramSpec) -> MediaOutput:
        # Generate Mermaid syntax
        if spec.type == "flowchart":
            mermaid_code = self._generate_flowchart(spec.data)
        elif spec.type == "sequence":
            mermaid_code = self._generate_sequence(spec.data)
        elif spec.type == "class":
            mermaid_code = self._generate_class(spec.data)

        # Render to image
        image_url = await mermaid_renderer.render(mermaid_code)

        return MediaOutput(
            url=image_url,
            metadata={
                "diagram_type": spec.type,
                "format": "png",
                "mermaid_syntax": mermaid_code
            }
        )

    def _generate_flowchart(self, data):
        lines = ["graph TD"]
        for step in data['steps']:
            lines.append(f"  {step['id']}[\"{step['label']}\"]")
        for edge in data['edges']:
            lines.append(f"  {edge['from']} --> {edge['to']}")
        return "\n".join(lines)
```

### Common Mistake: Not Awaiting Async Generators

```python
# ❌ WRONG - Not awaiting, loses result
image = image_generator.generate(spec)
# image is a coroutine, not the MediaOutput!

# ✅ CORRECT - Always await
image = await image_generator.generate(spec)
# image is now the MediaOutput
```

## Integration

### With Orchestration

```python
from cemaf.generation import ImageGenerator, AudioGenerator

# Agents use generators as tools
class MediaAgent:
    def __init__(self, image_gen: ImageGenerator, audio_gen: AudioGenerator):
        self.image_gen = image_gen
        self.audio_gen = audio_gen

    async def execute(self, task):
        # Generate image for campaign
        image = await self.image_gen.generate(task.image_spec)

        # Generate voiceover
        audio = await self.audio_gen.generate(task.audio_spec)

        return {
            "image": image.url,
            "audio": audio.url
        }
```

### With Context

```python
from cemaf.context.context import Context
from cemaf.generation import MediaOutput

# Record generated media in context
async def record_generation(output: MediaOutput, context: Context):
    # Add to context as artifact
    context.add_artifact({
        "type": "generated_media",
        "media_type": output.metadata["type"],
        "url": output.url,
        "metadata": output.metadata
    })
```

## API Reference

### Spec Classes

```python
@dataclass
class ImageSpec:
    prompt: str
    width: int = 1024
    height: int = 768
    style: str | None = None
    quality: str = "medium"
    negative_prompt: str | None = None

@dataclass
class AudioSpec:
    text: str
    voice: str
    language: str = "en-US"
    speaking_rate: float = 1.0
    emotion: str | None = None

@dataclass
class VideoSpec:
    script: str
    duration_seconds: int
    resolution: str = "720p"
    style: str = "cinematic"
    background_music: bool = True

@dataclass
class CodeSpec:
    description: str
    language: str
    style: str = "clean"
    complexity: str = "medium"
    libraries: list[str] = Field(default_factory=list)

@dataclass
class DiagramSpec:
    type: str  # flowchart, sequence, class, state
    data: dict
    style: str = "default"

@dataclass
class UISpec:
    description: str
    framework: str = "react"
    style: str = "modern"
    components: list[str] = Field(default_factory=list)
```

### MediaOutput

```python
@dataclass
class MediaOutput:
    url: str                           # URL or path
    metadata: dict = Field(default_factory=dict)
    thumbnail: str | None = None       # Preview URL
    usage: dict = Field(default_factory=dict)  # Tokens, cost, etc.
```

### Generator Protocols

```python
@runtime_checkable
class ImageGenerator(Protocol):
    async def generate(self, spec: ImageSpec) -> MediaOutput: ...

@runtime_checkable
class AudioGenerator(Protocol):
    async def generate(self, spec: AudioSpec) -> MediaOutput: ...

@runtime_checkable
class VideoGenerator(Protocol):
    async def generate(self, spec: VideoSpec) -> MediaOutput: ...

@runtime_checkable
class CodeGenerator(Protocol):
    async def generate(self, spec: CodeSpec) -> MediaOutput: ...

@runtime_checkable
class DiagramGenerator(Protocol):
    async def generate(self, spec: DiagramSpec) -> MediaOutput: ...

@runtime_checkable
class UIGenerator(Protocol):
    async def generate(self, spec: UISpec) -> MediaOutput: ...
```

## Best Practices

### Generator Selection

```python
# Choose generators based on requirements
GENERATORS = {
    "image": {
        "realistic": "OpenAI DALL-E",
        "style": "Midjourney",
        "fast": "Stable Diffusion local",
        "quality": "Leonardo.AI"
    },
    "audio": {
        "natural": "ElevenLabs",
        "cost-effective": "Google TTS",
        "emotional": "Respeecher"
    },
    "video": {
        "realistic": "Runway",
        "fast": "D-ID",
        "custom": "local ffmpeg"
    }
}
```

### Error Handling

```python
async def generate_with_fallback(spec, primary_gen, fallback_gen):
    try:
        return await primary_gen.generate(spec)
    except Exception as e:
        logger.warning(f"Primary generation failed: {e}")
        try:
            return await fallback_gen.generate(spec)
        except Exception as e2:
            logger.error(f"Fallback also failed: {e2}")
            raise
```

### Performance Tips

- **Cache generations**: Same spec = same output. Cache aggressively.
- **Batch requests**: Submit multiple generations in parallel
- **Monitor costs**: Generation APIs are expensive. Track and optimize
- **Progressive enhancement**: Generate lower quality first, upscale later if needed

### Common Pitfalls

**Over-complicated specs**: Keep specs simple. Generators don't understand nuance.

**Ignoring generation time**: Some generators are slow. Don't block on them.

**Cost explosion**: Generation is expensive. Monitor tokens/calls carefully.

**Quality inconsistency**: Same prompt might generate different quality. Test variations.

### When NOT to Use

- **Existing media**: Use those directly
- **Structured data**: Use code generators, not image generators
- **Real-time rendering**: Generators are asynchronous
- **Deterministic output**: Generators are non-deterministic by nature
