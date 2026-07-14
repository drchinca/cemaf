# Semantic Blueprints

Semantic blueprints provide structured prompt engineering based on Denis Rothman's approach. A blueprint defines **HOW** to accomplish a task, separate from **WHAT** data to use, enabling reusable, composable prompt templates.

## Overview

Blueprints are structured templates that guide LLM behavior through:

- **Scene Goals**: Objectives and success criteria
- **Style Guides**: Tone, format, and vocabulary preferences
- **Context Entities**: Roles, personas, or components
- **Instructions**: Detailed task specifications
- **Policies**: Output contracts, execution policies, security policies

## Core Components

### Blueprint

The main `Blueprint` class combines all elements:

```python
from cemaf.blueprint import Blueprint, SceneGoal, StyleGuide

blueprint = Blueprint(
    id="blog_post_generator",
    name="Blog Post Generator",
    scene_goal=SceneGoal(
        objective="Generate an engaging blog post about AI",
        success_criteria=("informative", "engaging", "well-structured"),
        constraints=("under 1000 words", "no technical jargon"),
        priority=1,
    ),
    style_guide=StyleGuide(
        tone="professional",
        format="markdown",
        length_hint="detailed",
        vocabulary=("AI", "machine learning", "neural networks"),
        avoid=("jargon", "acronyms"),
    ),
    instruction="Write a comprehensive blog post that explains AI concepts...",
)
```

### SceneGoal

Defines the objective and constraints:

```python
from cemaf.blueprint import SceneGoal

goal = SceneGoal(
    objective="Analyze customer feedback",
    success_criteria=("identify themes", "prioritize issues"),
    constraints=("use data from Q4", "focus on high-priority items"),
    priority=1,
)
```

### StyleGuide

Controls tone, format, and style:

```python
from cemaf.blueprint import StyleGuide

style = StyleGuide(
    tone="professional",
    format="markdown",
    length_hint="concise",
    vocabulary=("customer", "satisfaction", "improvement"),
    avoid=("slang", "jargon"),
    examples=("Example 1...", "Example 2..."),
)
```

### ContextEntity

Represents roles, personas, or components in the blueprint:

```python
from cemaf.blueprint import ContextEntity

# Content generation role
writer = ContextEntity.content(
    name="technical_writer",
    description="Create clear technical documentation",
    style="technical",
    traits=("precise", "clear"),
)

# Analysis role
analyst = ContextEntity.analysis(
    name="data_analyst",
    methodology="quantitative",
    depth="comprehensive",
)

# Technical role
engineer = ContextEntity.technical(
    name="code_reviewer",
    domain="software",
    audience_level="advanced",
)
```

## Usage Patterns

### Pattern 1: Simple Content Generation

```python
blueprint = Blueprint(
    id="simple_generator",
    name="Simple Generator",
    scene_goal=SceneGoal(objective="Generate content"),
    style_guide=StyleGuide(tone="professional"),
)

prompt = blueprint.to_prompt()
```

### Pattern 2: Structured Analysis

```python
blueprint = Blueprint(
    id="analysis",
    name="Data Analysis",
    scene_goal=SceneGoal(
        objective="Analyze sales data",
        success_criteria=("identify trends", "provide insights"),
    ),
    entities=(
        ContextEntity.analysis(
            name="analyst",
            methodology="quantitative",
        ),
    ),
    instruction="Analyze the provided data and identify key trends...",
)
```

### Pattern 3: Multi-Entity Composition

```python
blueprint = Blueprint(
    id="multi_entity",
    name="Multi-Entity Blueprint",
    scene_goal=SceneGoal(objective="Generate collaborative content"),
    entities=(
        ContextEntity.content(name="writer", style="narrative"),
        ContextEntity.content(name="editor", style="technical"),
    ),
)
```

## Integration with Context Compilation

Blueprints can inform context compilation priorities:

```python
from cemaf.context import PriorityContextCompiler
from cemaf.blueprint import Blueprint

blueprint = Blueprint(...)

# Get context priorities from blueprint
priorities = blueprint.get_context_priorities()

# Use in context compilation
compiler = PriorityContextCompiler(estimator)
compiled = compiler.compile(
    artifacts=artifacts,
    memories=memories,
    budget=budget,
    priorities=priorities,  # Blueprint-informed priorities
)
```

## Policies and Contracts

### OutputContract

Defines expected output structure:

```python
from cemaf.blueprint import OutputContract, DataContract

data_contract = DataContract(
    schema_type="object",
    fields=("title", "content"),
    required_fields=("title", "content"),
)

contract = OutputContract(
    format="json",
    required_sections=("title", "content"),
    schema_definition='{"type":"object","required":["title","content"]}',
)
```

### ExecutionPolicy

Defines execution constraints:

```python
from cemaf.blueprint import ExecutionPolicy

policy = ExecutionPolicy(
    incremental_strategy="checkpoint",
    checkpoint_location="s3://bucket/checkpoints",
    max_retries=3,
    retry_on=("rate_limit", "transient_network", "timeout"),
)
```

### SecurityPolicy

Defines security requirements:

```python
from cemaf.blueprint import SecurityPolicy

security = SecurityPolicy(
    pii_fields=("email", "phone"),
    encryption="at_rest_and_in_transit",
    secret_provider="vault",
    compliance_frameworks=("GDPR", "SOC2"),
)
```

## Prompt Generation

Convert blueprint to prompt string:

```python
prompt = blueprint.to_prompt()

# Prompt includes:
# - Goal section
# - Style section (if non-empty)
# - Entities section (if entities present)
# - Instruction section (if provided)
# - Metadata section (if metadata present)
```

## Builder Methods

Use `BlueprintBuilder` for common patterns:

```python
from cemaf.blueprint import BlueprintBuilder

# Content generation blueprint
content_bp = (
    BlueprintBuilder("blog", "Blog Post")
    .with_goal("Generate blog post")
    .with_style(tone="professional", format="markdown")
    .with_instruction("Write a concise post with a clear title and sections.")
    .build()
)

# Analysis blueprint
analysis_bp = (
    BlueprintBuilder("sales_analysis", "Sales Analysis")
    .with_goal("Analyze sales data", success_criteria=["identify trends"])
    .with_style(tone="analytical", format="markdown")
    .with_instruction("Summarize findings, drivers, and risks.")
    .build()
)
```

## Integration Examples

### Example 1: Blueprint + LLM

```python
from cemaf.llm import LLMClient
from cemaf.blueprint import Blueprint

llm = LLMClient(...)
blueprint = Blueprint(...)

prompt = blueprint.to_prompt()
response = await llm.complete(prompt)
```

### Example 2: Blueprint + Context Compiler

```python
from cemaf.context import PriorityContextCompiler
from cemaf.blueprint import Blueprint

blueprint = Blueprint(...)
compiler = PriorityContextCompiler(...)

# Blueprint informs context priorities
priorities = blueprint.get_context_priorities()
compiled = compiler.compile(..., priorities=priorities)
```

### Example 3: Blueprint + MCP

```python
from cemaf.mcp import MCPAdapter
from cemaf.blueprint import Blueprint

blueprints = [blueprint1, blueprint2]
adapter = MCPAdapter(blueprints=blueprints)

# Blueprints exposed as MCP prompts:
# - blueprint://blog_post_generator
```

## Best Practices

1. **Separate HOW from WHAT**: Blueprints define process, not data
2. **Use clear objectives**: Make scene goals specific and measurable
3. **Define style consistently**: Use style guides for consistent output
4. **Compose entities**: Use multiple entities for complex scenarios
5. **Add policies**: Use contracts and policies for production use
6. **Reuse blueprints**: Create reusable templates for common tasks
7. **Version blueprints**: Track blueprint versions for reproducibility

## Entity Types

### Content Entities

For content generation (storytelling, articles, creative writing):

```python
writer = ContextEntity.content(
    name="writer",
    style="narrative",
    perspective="third-person",
    traits=("creative", "engaging"),
)
```

### Analysis Entities

For data analysis, research, evaluation:

```python
analyst = ContextEntity.analysis(
    name="analyst",
    methodology="quantitative",
    depth="comprehensive",
    bias_awareness="objective",
)
```

### Technical Entities

For code, documentation, technical specs:

```python
engineer = ContextEntity.technical(
    name="engineer",
    domain="software",
    audience_level="advanced",
    knowledge_level="expert",
)
```

### Comparative Entities

For compare/contrast scenarios:

```python
comparator = ContextEntity.comparative(
    name="comparator",
    format="side-by-side",
    bias_awareness="neutral",
)
```

### Educational Entities

For teaching, explaining concepts:

```python
teacher = ContextEntity.educational(
    name="teacher",
    style="socratic",
    audience_level="beginner",
)
```

### Validation Entities

For compliance checking, verification:

```python
validator = ContextEntity.validation(
    name="validator",
    validation_type="compliance",
    knowledge_level="expert",
)
```

## Related Modules

- **Generation**: Blueprints guide content generation
- **Context**: Blueprints inform context compilation priorities
- **MCP**: Blueprints exposed as MCP prompts
- **LLM**: Blueprints converted to prompts for LLM consumption
- **Validation**: Output contracts validate blueprint outputs
