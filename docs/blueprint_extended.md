# Blueprint Module: Semantic Blueprints for Structured Generation

## Overview

The `blueprint` module provides **semantic specifications for structured content generation**, enabling LLMs to produce consistent, well-formed outputs aligned with predefined goals, styles, and entity types.

**Key Purpose**: Guide LLM generation toward specific structure and tone
**Main Components**: `Blueprint`, `SceneGoal`, `StyleGuide`, `ContextEntity`
**When to Use**: When you need consistent, structured LLM output

---

## Core Concepts

### Scene Goals

```python
from cemaf.blueprint import SceneGoal, GoalType

# Define what the generation should accomplish
goal = SceneGoal(
    type=GoalType.NARRATIVE,  # What kind of output
    description="Write a product launch announcement",
    requirements=[
        "Mention key features",
        "Include pricing",
        "End with call-to-action",
    ],
)
```

### Style Guide

```python
from cemaf.blueprint import StyleGuide, Tone, Formality

# Define how the content should sound
style = StyleGuide(
    tone=Tone.PROFESSIONAL,
    formality=Formality.FORMAL,
    key_phrases=[
        "innovative solution",
        "customer-centric",
        "enterprise-grade",
    ],
    forbidden_phrases=[
        "obviously",
        "it's pretty cool",
    ],
    voice_characteristics="authoritative but approachable",
)
```

### Entity Types

```python
from cemaf.blueprint import ContextEntity, EntityType

# Define content entities for structured generation
entities = [
    ContextEntity(
        type=EntityType.PRODUCT,
        name="CloudDB Pro",
        attributes={
            "features": ["scaling", "security", "compliance"],
            "price": "$99/month",
        },
    ),
    ContextEntity(
        type=EntityType.PERSON,
        name="Alex Chen",
        attributes={
            "role": "CTO",
            "expertise": ["cloud architecture", "security"],
        },
    ),
]
```

### Blueprint

```python
from cemaf.blueprint import Blueprint

# Combine into complete blueprint
blueprint = Blueprint(
    goal=goal,
    style=style,
    entities=entities,
    constraints={
        "max_length": 500,
        "include_section": ["features", "pricing"],
        "exclude_section": ["technical_details"],
    },
)
```

---

## Usage Examples

### Basic Blueprint Generation

```python
from cemaf.blueprint import Blueprint, SceneGoal, StyleGuide
from cemaf.llm import LLMClient, Message, Role

async def generate_with_blueprint(
    llm: LLMClient,
    blueprint: Blueprint,
) -> str:
    """Generate content following blueprint."""

    prompt = f"""Generate content following these guidelines:

Goal: {blueprint.goal.description}
Requirements: {blueprint.goal.requirements}

Tone: {blueprint.style.tone.value}
Voice: {blueprint.style.voice_characteristics}

Key phrases to include: {blueprint.style.key_phrases}
Phrases to avoid: {blueprint.style.forbidden_phrases}

Entities to mention: {[e.name for e in blueprint.entities]}

Constraints:
{json.dumps(blueprint.constraints, indent=2)}

Generate the content:
"""

    result = await llm.complete([
        Message(role=Role.USER, content=prompt)
    ])

    return result.text
```

### Product Description Generation

```python
from cemaf.blueprint import (
    Blueprint,
    SceneGoal,
    StyleGuide,
    GoalType,
    Tone,
    Formality,
    ContextEntity,
    EntityType,
)

# Define blueprint for product description
goal = SceneGoal(
    type=GoalType.DESCRIPTIVE,
    description="Write product description for e-commerce",
    requirements=[
        "Highlight unique features",
        "Explain benefits to customer",
        "Include specifications",
        "Call to action at end",
    ],
)

style = StyleGuide(
    tone=Tone.PERSUASIVE,
    formality=Formality.SEMI_FORMAL,
    key_phrases=[
        "innovative design",
        "premium quality",
        "trusted choice",
    ],
)

product = ContextEntity(
    type=EntityType.PRODUCT,
    name="ProCamera Pro Max",
    attributes={
        "features": ["AI autofocus", "8K video", "night mode"],
        "price": "$1,299",
        "warranty": "2 years",
    },
)

blueprint = Blueprint(
    goal=goal,
    style=style,
    entities=[product],
    constraints={"max_length": 300},
)

# Generate
description = await generate_with_blueprint(llm, blueprint)
```

### Email Campaign Blueprint

```python
# Email blueprint with multiple entities
email_goal = SceneGoal(
    type=GoalType.MARKETING,
    description="Craft promotional email",
    requirements=[
        "Compelling subject line",
        "Personal greeting",
        "Value proposition",
        "Social proof",
        "Clear CTA",
    ],
)

email_style = StyleGuide(
    tone=Tone.FRIENDLY,
    formality=Formality.INFORMAL,
    key_phrases=[
        "limited time offer",
        "join thousands of happy customers",
        "don't miss out",
    ],
)

recipient = ContextEntity(
    type=EntityType.PERSON,
    name="Alex",
    attributes={"segment": "premium", "interests": ["productivity"]},
)

offer = ContextEntity(
    type=EntityType.PROMOTION,
    name="50% off annual plan",
    attributes={"valid_until": "2026-02-22", "code": "SAVE50"},
)

email_blueprint = Blueprint(
    goal=email_goal,
    style=email_style,
    entities=[recipient, offer],
    constraints={
        "sections": ["subject", "body", "cta"],
        "tone_consistency": True,
    },
)
```

### Anti-Pattern: Vague Blueprints

```python
# ❌ WRONG - Too vague
vague_goal = SceneGoal(
    type=GoalType.NARRATIVE,
    description="Write something nice",  # Too vague
    requirements=["Make it good"],  # Unclear
)

# ✅ RIGHT - Specific and clear
clear_goal = SceneGoal(
    type=GoalType.NARRATIVE,
    description="Write product announcement for SaaS tool",
    requirements=[
        "Explain problem solved",
        "Highlight three key features",
        "Include pricing tiers",
        "End with 'Get started free' CTA",
    ],
)
```

---

## Integration

### With Context Compilation

```python
from cemaf.context import Context, ContextSource

# Blueprint can inform context selection
async def build_context_with_blueprint(blueprint: Blueprint) -> Context:
    """Build context prioritized for blueprint requirements."""

    sources = []

    # Add entity information as high-priority sources
    for entity in blueprint.entities:
        sources.append(
            ContextSource(
                id=f"entity:{entity.name}",
                content=json.dumps(entity.attributes),
                priority=0.9,  # High priority
                metadata={"entity_type": entity.type.value},
            )
        )

    # Add style guide as medium priority
    style_content = f"""
    Tone: {blueprint.style.tone.value}
    Key phrases: {', '.join(blueprint.style.key_phrases)}
    Avoid: {', '.join(blueprint.style.forbidden_phrases)}
    """

    sources.append(
        ContextSource(
            id="style_guide",
            content=style_content,
            priority=0.7,
        )
    )

    # Compile with blueprint-aware priorities
    return compiler.compile(
        sources=sources,
        budget=TokenBudget.from_total(2000),
    )
```

### With RLM (for Large Content)

```python
# Use RLM to extract relevant information for blueprint
async def rlm_blueprint_generation(
    rlm: RLMQueryTool,
    blueprint: Blueprint,
    large_document: str,
) -> str:
    """Query large document using blueprint requirements."""

    # Ask RLM to extract entities and information
    instruction = f"""
    Extract information relevant to this blueprint:
    Goal: {blueprint.goal.description}
    Entities needed: {[e.name for e in blueprint.entities]}
    Requirements: {blueprint.goal.requirements}

    Return structured information.
    """

    extracted = await rlm.execute(
        instruction=instruction,
        content=large_document,
    )

    # Use extracted data in generation
    return await generate_with_blueprint(llm, blueprint, extracted)
```

### With Tools

```python
from cemaf.tools import Tool, ToolResult

class BlueprintGeneratorTool(Tool):
    """Tool that generates content from blueprint."""

    async def execute(self, blueprint: Blueprint, **kwargs) -> ToolResult:
        """Execute blueprint-driven generation."""
        content = await generate_with_blueprint(self.llm, blueprint)
        return ToolResult(success=True, data=content)
```

---

## API Reference

### Blueprint

```python
@dataclass(frozen=True)
class Blueprint:
    goal: SceneGoal
    style: StyleGuide
    entities: list[ContextEntity]
    constraints: dict | None = None

    def get_prompt_template(self) -> str:
        """Generate prompt template from blueprint."""
        # Returns formatted prompt for LLM
```

### SceneGoal

```python
@dataclass(frozen=True)
class SceneGoal:
    type: GoalType  # Type of generation
    description: str  # What to generate
    requirements: list[str]  # Specific requirements

    # GoalType options
    # NARRATIVE, DESCRIPTIVE, PERSUASIVE, INFORMATIVE, CREATIVE, MARKETING
```

### StyleGuide

```python
@dataclass(frozen=True)
class StyleGuide:
    tone: Tone
    formality: Formality
    key_phrases: list[str]
    forbidden_phrases: list[str]
    voice_characteristics: str

    # Tone: PROFESSIONAL, FRIENDLY, FORMAL, CASUAL, PERSUASIVE
    # Formality: FORMAL, SEMI_FORMAL, INFORMAL, CASUAL
```

### ContextEntity

```python
@dataclass(frozen=True)
class ContextEntity:
    type: EntityType
    name: str
    attributes: dict[str, Any]

    # EntityType: PRODUCT, PERSON, COMPANY, PLACE, EVENT, CONCEPT, ...
```

---

## Best Practices

### 1. Specific, Measurable Requirements

```python
# ✅ GOOD - Specific and measurable
goal = SceneGoal(
    type=GoalType.MARKETING,
    description="Write product announcement",
    requirements=[
        "Exactly 3 key benefits mentioned",
        "Price clearly stated",
        "Include customer testimonial",
        "End with specific CTA: 'Start 14-day free trial'",
    ],
)

# ❌ BAD - Vague
goal = SceneGoal(
    type=GoalType.MARKETING,
    description="Write marketing stuff",
    requirements=["Make it compelling"],
)
```

### 2. Entity Information Complete

```python
# ✅ GOOD - Rich attributes
product = ContextEntity(
    type=EntityType.PRODUCT,
    name="CloudDB Pro",
    attributes={
        "features": ["auto-scaling", "99.99% uptime", "AES-256 encryption"],
        "pricing": {
            "starter": "$29/month",
            "pro": "$99/month",
            "enterprise": "custom",
        },
        "target_users": "developers, DevOps engineers",
        "differentiators": ["fastest query execution", "lowest latency"],
    },
)

# ❌ BAD - Minimal attributes
product = ContextEntity(
    type=EntityType.PRODUCT,
    name="CloudDB Pro",
    attributes={"price": "$99"},
)
```

### 3. Consistent Tone Across Entities

```python
# ✅ GOOD - Consistent style
style = StyleGuide(
    tone=Tone.PROFESSIONAL,
    formality=Formality.FORMAL,
    key_phrases=["enterprise-grade", "mission-critical", "production-ready"],
    forbidden_phrases=["cool", "awesome", "pretty good"],
)

# ❌ BAD - Inconsistent
# Using both formal entity names and casual language
# Will confuse LLM about desired tone
```

### 4. Constraint Clarity

```python
# ✅ GOOD - Clear constraints
constraints = {
    "max_length": 300,  # Character limit
    "min_sections": 3,  # Minimum sections
    "include_keywords": ["innovation", "reliability"],
    "reading_level": "high school",
    "no_superlatives": False,
}

# ❌ BAD - Ambiguous
constraints = {
    "make_it_concise": True,  # How concise?
    "be_persuasive": True,  # How persuasive?
}
```

### 5. Entity Relevance

```python
# ✅ GOOD - All entities relevant to goal
goal = SceneGoal(
    type=GoalType.PRODUCT_COMPARISON,
    description="Compare two project management tools",
)

entities = [
    ContextEntity(type=EntityType.PRODUCT, name="Tool A", attributes=...),
    ContextEntity(type=EntityType.PRODUCT, name="Tool B", attributes=...),
    ContextEntity(type=EntityType.PERSON, name="User Persona", attributes=...),
]

# ❌ BAD - Irrelevant entities
entities = [
    ContextEntity(type=EntityType.PRODUCT, name="Coffee Maker", attributes=...),
    # Why is coffee maker relevant to project management?
]
```

---

## Common Patterns

### Pattern 1: Multi-Language Blueprint

```python
async def generate_multilingual(
    blueprint: Blueprint,
    languages: list[str],
) -> dict[str, str]:
    """Generate content in multiple languages."""
    results = {}

    for language in languages:
        localized_blueprint = Blueprint(
            goal=blueprint.goal,
            style=blueprint.style,
            entities=blueprint.entities,
            constraints={
                **blueprint.constraints,
                "language": language,
            },
        )

        results[language] = await generate_with_blueprint(
            llm,
            localized_blueprint,
        )

    return results
```

### Pattern 2: A/B Testing with Blueprints

```python
async def generate_ab_variants(
    base_blueprint: Blueprint,
) -> dict[str, str]:
    """Generate A/B test variants with different styles."""

    variants = {}

    # Variant A: Formal, technical
    formal_blueprint = Blueprint(
        goal=base_blueprint.goal,
        style=StyleGuide(
            tone=Tone.PROFESSIONAL,
            formality=Formality.FORMAL,
            key_phrases=["advanced", "technical", "scalable"],
        ),
        entities=base_blueprint.entities,
    )
    variants["technical"] = await generate_with_blueprint(llm, formal_blueprint)

    # Variant B: Friendly, simple
    friendly_blueprint = Blueprint(
        goal=base_blueprint.goal,
        style=StyleGuide(
            tone=Tone.FRIENDLY,
            formality=Formality.INFORMAL,
            key_phrases=["easy", "simple", "accessible"],
        ),
        entities=base_blueprint.entities,
    )
    variants["friendly"] = await generate_with_blueprint(llm, friendly_blueprint)

    return variants
```

### Pattern 3: Blueprint Validation

```python
async def validate_blueprint_output(
    blueprint: Blueprint,
    output: str,
) -> tuple[bool, list[str]]:
    """Validate output meets blueprint requirements."""

    issues = []

    # Check length constraint
    if "max_length" in blueprint.constraints:
        max_len = blueprint.constraints["max_length"]
        if len(output) > max_len:
            issues.append(f"Output exceeds max length ({len(output)} > {max_len})")

    # Check required keywords
    if "include_keywords" in blueprint.constraints:
        for keyword in blueprint.constraints["include_keywords"]:
            if keyword.lower() not in output.lower():
                issues.append(f"Missing required keyword: {keyword}")

    # Check forbidden phrases
    for phrase in blueprint.style.forbidden_phrases:
        if phrase.lower() in output.lower():
            issues.append(f"Contains forbidden phrase: {phrase}")

    return len(issues) == 0, issues
```

---

## Troubleshooting

### Issue: LLM Ignores Blueprint

```python
# Problem: Generated content doesn't follow blueprint
# Solution: Make blueprint requirements explicit in prompt

# Iterate if needed
for attempt in range(3):
    output = await generate_with_blueprint(llm, blueprint)
    valid, issues = await validate_blueprint_output(blueprint, output)

    if valid:
        return output

    # Add issues to prompt for next attempt
    logger.warning(f"Attempt {attempt} failed: {issues}")
    # Retry with stricter constraints
```

### Issue: Inconsistent Tone

```python
# Problem: Generated content has mixed tone
# Solution: Stronger tone specification

# Add tone example
style = StyleGuide(
    tone=Tone.PROFESSIONAL,
    formality=Formality.FORMAL,
    tone_example="""
    Example professional tone:
    "We've engineered a robust solution..."
    NOT: "We made something pretty cool..."
    """,
)
```

### Issue: Entity Information Lost

```python
# Problem: Generated content missing entity details
# Solution: Include entities in prompt more prominently

instruction = f"""
IMPORTANT: Mention the following details:
{json.dumps([e.attributes for e in blueprint.entities], indent=2)}

Generate content:
...
"""
```

---

## Configuration

```yaml
blueprint:
  default_goal_type: NARRATIVE
  default_style:
    tone: PROFESSIONAL
    formality: SEMI_FORMAL
  max_output_length: 500
  validation_strict: true
```

---

**Related Documentation**:
- [Context Module](./context.md) - Context prioritization
- [LLM Module](./llm.md) - Generation with blueprints
- [RLM Module](./rlm.md) - Large-content blueprint queries
- [Tools Module](./tools.md) - Blueprint as tool input
