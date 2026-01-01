# Generation

Protocols for generative AI outputs: images, audio, video, UI, and code.

## Generation Architecture

```mermaid
flowchart TB
    subgraph Generators
        IMG[ImageGenerator<br/>Images]
        AUDIO[AudioGenerator<br/>Sound/Speech]
        VIDEO[VideoGenerator<br/>Video clips]
        UI[UIGenerator<br/>Components]
        CODE[CodeGenerator<br/>Source code]
    end

    subgraph Specs
        IMGSPEC[ImageSpec<br/>prompt, size, style]
        CODESPEC[CodeSpec<br/>language, requirements]
    end

    subgraph Output
        RESULT[GenerationResult<br/>content, metadata]
    end

    IMGSPEC --> IMG
    CODESPEC --> CODE
    IMG --> RESULT
    AUDIO --> RESULT
    VIDEO --> RESULT
    UI --> RESULT
    CODE --> RESULT
```

## Generation Flow

```mermaid
sequenceDiagram
    participant Client
    participant Generator as ImageGenerator
    participant API as Generation API
    participant Result

    Client->>Generator: generate(ImageSpec)
    Note over Generator: Validate spec
    Generator->>API: Request generation
    API-->>Generator: Generated content

    alt Success
        Generator-->>Client: GenerationResult(content)
    else Error
        Generator-->>Client: Result.fail(error)
    end
```

## Image Generation

```python
from cemaf.generation.protocols import ImageGenerator, ImageSpec

generator: ImageGenerator = DalleGenerator()

spec = ImageSpec(
    prompt="A beautiful sunset",
    size="1024x1024",
    style="photorealistic"
)

result = await generator.generate(spec)
```

## Code Generation

```python
from cemaf.generation.protocols import CodeGenerator, CodeSpec

generator: CodeGenerator = ClaudeCodeGenerator()

spec = CodeSpec(
    language="python",
    requirements="Create a function that calculates fibonacci",
    include_tests=True
)

result = await generator.generate(spec)
```
