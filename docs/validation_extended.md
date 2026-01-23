# Validation Module - Extended Documentation

## Overview

The validation module provides business rule validation with pluggable rules, repair suggestions, and pipeline aggregation for complex validation scenarios.

**What it does**: Defines validation rules (required fields, length, regex, JSON schema, custom logic) and pipelines that run multiple rules, collect errors/warnings, suggest repairs, and determine overall validity. Rules are composable and reusable across different contexts.

**Key use cases**:
- Validate content before publishing (length, required fields, format)
- Enforce business rules (min/max values, allowed values, patterns)
- Check structured data conformance (JSON schemas, dataclass validation)
- Suggest repairs for common issues (truncate long text, fill defaults)
- A/B test different validation policies
- Validate user input before processing

**When to use vs. alternatives**: Use validation for business logic constraints and data shape requirements. Use moderation for content safety. Use schema validation libraries for pure JSON/data validation (though module wraps them).

## Core Concepts

### Rule Types

**Required Fields Rule**: Check that all mandatory fields exist and aren't empty. Essential for structural validation.

**Length Rule**: Enforce min/max length constraints. Platform-specific (Twitter 280 chars, etc.).

**Range Rule**: Enforce numeric bounds. Price ranges, quantity limits, etc.

**Regex Rule**: Pattern matching for format validation. Email, phone, URLs, etc.

**Schema Rule**: Pydantic or JSON schema validation for complex structures.

**Custom Rule**: User-defined validation logic for business-specific rules.

Each rule returns ValidationError if it fails, with message and optional repair suggestion.

### Validation Severity

**ERROR**: Validation fails, content cannot proceed. Hard stop.

**WARNING**: Issue noted but content can continue. Needs human review.

**INFO**: Informational only, doesn't affect decision.

Pipelines aggregate violations by severity and determine if overall validation passes.

### Repair Suggestions

When validation fails, rules can suggest repairs:

**LengthRule**: "Truncate to 280 characters" - auto-repairable
**Required Fields**: "Add missing field 'title'" - suggests value
**RegexRule**: "Invalid email format. Did you mean...?" - suggests correction
**Custom**: Any domain-specific repair logic

## Usage Examples

### Basic Content Validation

```python
from cemaf.validation import (
    ValidationPipeline,
    RequiredFieldsRule,
    LengthRule,
    RegexRule,
)
from cemaf.validation.protocols import ValidationSeverity

# Create validation rules for social post
post_validator = ValidationPipeline([
    RequiredFieldsRule(
        required=["title", "body"],
        severity=ValidationSeverity.ERROR
    ),
    LengthRule(
        field="body",
        max_length=280,
        severity=ValidationSeverity.ERROR
    ),
    LengthRule(
        field="title",
        min_length=5,
        max_length=100,
        severity=ValidationSeverity.WARNING
    ),
])

# Validate post
post = {"title": "A", "body": "Check out our new product!"}
result = await post_validator.validate(post)

if result.valid:
    print("✓ Post is valid")
else:
    print("✗ Post validation failed:")
    for error in result.errors:
        print(f"  {error.severity}: {error.message}")
        if error.repair_suggestion:
            print(f"    Suggestion: {error.repair_suggestion}")
```

### Platform-Specific Validation

```python
# Different rules for different platforms
def create_platform_validator(platform: str):
    if platform == "twitter":
        return ValidationPipeline([
            LengthRule(field="body", max_length=280),
            RequiredFieldsRule(required=["body"]),
            RegexRule(field="hashtags", pattern=r"^#\w+$"),
        ])

    elif platform == "linkedin":
        return ValidationPipeline([
            LengthRule(field="body", max_length=3000),
            RequiredFieldsRule(required=["title", "body"]),
            RegexRule(field="title", pattern=r"^[A-Za-z].*[A-Za-z0-9]$"),
        ])

    elif platform == "instagram":
        return ValidationPipeline([
            LengthRule(field="caption", max_length=2200),
            RequiredFieldsRule(required=["caption", "media"]),
        ])

# Use platform validator
content = {"body": "Test", ...}
validator = create_platform_validator("twitter")
result = await validator.validate(content)
```

### Repair and Retry

```python
# Try to repair common issues
content = {"title": "", "body": "x", "hashtags": "#"}
result = await validator.validate(content)

if not result.valid:
    # Attempt repairs
    repaired = content.copy()

    for error in result.errors:
        if error.repair_suggestion:
            # Apply auto-repair
            if "Truncate" in error.repair_suggestion:
                repaired["body"] = content["body"][:280]
            elif "missing" in error.repair_suggestion:
                repaired[error.field] = "Default Value"

    # Re-validate repaired version
    result = await validator.validate(repaired)

    if result.valid:
        print("✓ Repaired successfully")
        content = repaired
```

### Schema Validation

```python
from cemaf.validation import SchemaRule
from pydantic import BaseModel

# Define expected structure
class PublishRequest(BaseModel):
    title: str
    body: str
    platform: str
    scheduled_at: datetime | None = None

# Validate against schema
schema_validator = ValidationPipeline([
    SchemaRule(schema=PublishRequest),
])

request_data = {
    "title": "Post Title",
    "body": "Post content",
    "platform": "twitter",
    "extra_field": "should be ignored"
}

result = await schema_validator.validate(request_data)
if result.valid:
    parsed = PublishRequest(**request_data)
```

### Custom Business Rules

```python
from cemaf.validation.protocols import Rule, ValidationError, ValidationSeverity

class BrandGuidelinesRule(Rule):
    """Enforce brand-specific validation rules."""

    async def validate(self, content: dict) -> ValidationError | None:
        body = content.get("body", "")

        # Brand rule 1: No all-caps
        if body.isupper():
            return ValidationError(
                field="body",
                message="Content is all uppercase",
                severity=ValidationSeverity.WARNING,
                repair_suggestion=body.capitalize()
            )

        # Brand rule 2: Include call-to-action
        has_cta = any(cta in body.lower() for cta in ["check out", "learn more", "click here"])
        if not has_cta:
            return ValidationError(
                field="body",
                message="Missing call-to-action",
                severity=ValidationSeverity.WARNING,
                repair_suggestion=f"{body} Learn more →"
            )

        return None

# Use custom rule
brand_validator = ValidationPipeline([
    BrandGuidelinesRule(),
])

result = await brand_validator.validate({"body": "buy our product"})
```

### Conditional Validation

```python
# Rules depend on platform and content type
class ConditionalValidator:
    async def validate(self, content: dict) -> ValidationResult:
        platform = content.get("platform")
        content_type = content.get("type")

        rules = [RequiredFieldsRule(required=["body"])]

        # Add platform-specific rules
        if platform == "twitter":
            rules.append(LengthRule(field="body", max_length=280))
        elif platform == "linkedin":
            rules.append(LengthRule(field="body", max_length=3000))
            if content_type == "article":
                rules.append(RequiredFieldsRule(required=["title"]))

        # Add content-type specific rules
        if content_type == "video":
            rules.append(RequiredFieldsRule(required=["duration_seconds"]))
            rules.append(RangeRule(field="duration_seconds", min=5, max=600))

        validator = ValidationPipeline(rules)
        return await validator.validate(content)
```

### Common Mistake: Ignoring Warnings

```python
# ❌ WRONG - Treat warnings same as errors
result = await validator.validate(content)
if not result.valid:
    return None  # Reject for warnings too

# ✅ CORRECT - Only reject for errors, queue warnings for review
result = await validator.validate(content)

if any(e.severity == ValidationSeverity.ERROR for e in result.errors):
    return None  # Hard error, reject

if result.errors:
    # Has warnings, queue for human review
    await review_queue.add(content, violations=result.errors)

# Continue with content
```

## Integration

### With Content Publishing

```python
from cemaf.persistence.entities import ContentStatus

async def publish_with_validation(content_item, validators):
    """Only publish content that validates."""
    # Validate against platform rules
    platform_validator = validators[content_item.platform]
    result = await platform_validator.validate({
        "title": content_item.title,
        "body": content_item.body,
        "platform": content_item.platform
    })

    if not result.valid:
        # Hard errors - reject
        if any(e.severity == ValidationSeverity.ERROR for e in result.errors):
            return content_item.with_status(ContentStatus.FAILED)

        # Warnings - queue for review
        return content_item.with_status(ContentStatus.PENDING_REVIEW)

    # Valid - approve
    return content_item.with_status(ContentStatus.APPROVED)
```

### With Generation Module

```python
from cemaf.generation.protocols import ContentGenerator

class ValidatedGenerator:
    """Generator that validates outputs."""

    def __init__(self, generator: ContentGenerator, validator):
        self.generator = generator
        self.validator = validator

    async def generate_valid_content(self, prompt: str):
        """Generate content that passes validation."""
        for attempt in range(3):
            content = await self.generator.generate(prompt)
            result = await self.validator.validate(content)

            if result.valid:
                return content

            if result.errors and result.errors[0].repair_suggestion:
                # Regenerate with repair suggestion in prompt
                prompt = f"{prompt}. {result.errors[0].repair_suggestion}"

        raise ValueError("Failed to generate valid content")
```

### With Moderation Module

```python
from cemaf.moderation import ModerationPipeline

# Combine validation and moderation
class ComprehensiveValidator:
    def __init__(self, validation_rules, moderation_rules):
        self.validation = ValidationPipeline(validation_rules)
        self.moderation = ModerationPipeline(moderation_rules)

    async def validate_content(self, content: dict):
        """Check both business rules and content safety."""
        # Business validation
        val_result = await self.validation.validate(content)
        if not val_result.valid:
            return {"valid": False, "reason": "validation_failed", "errors": val_result.errors}

        # Content safety
        mod_result = await self.moderation.moderate(content["body"])
        if not mod_result.safe:
            return {"valid": False, "reason": "moderation_failed", "violations": mod_result.violations}

        return {"valid": True}
```

## API Reference

### Rule Protocol

```python
@runtime_checkable
class Rule(Protocol):
    async def validate(self, data: Any) -> ValidationError | None:
        """Validate data. Return None if valid, ValidationError if invalid."""
```

### ValidationError Dataclass

```python
@dataclass
class ValidationError:
    field: str | None = None
    message: str
    severity: ValidationSeverity = ERROR
    repair_suggestion: str | None = None
    context: str | None = None
```

### ValidationResult Dataclass

```python
@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(e.severity == ValidationSeverity.ERROR for e in self.errors)

    @property
    def has_warnings(self) -> bool:
        return any(e.severity == ValidationSeverity.WARNING for e in self.errors)
```

### Rule Implementations

```python
class RequiredFieldsRule(Rule):
    def __init__(self, required: list[str], severity=ERROR): ...

class LengthRule(Rule):
    def __init__(
        self,
        field: str | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        severity=ERROR
    ): ...

class RangeRule(Rule):
    def __init__(
        self,
        field: str,
        min: float | None = None,
        max: float | None = None,
        severity=ERROR
    ): ...

class RegexRule(Rule):
    def __init__(
        self,
        field: str,
        pattern: str,
        severity=ERROR
    ): ...

class SchemaRule(Rule):
    def __init__(self, schema: type, severity=ERROR): ...

class CustomRule(Rule):
    def __init__(self, validation_fn: Callable, severity=ERROR): ...
```

### ValidationPipeline

```python
class ValidationPipeline:
    def __init__(self, rules: list[Rule]): ...

    async def validate(self, data: Any) -> ValidationResult:
        """Run all rules, collect errors."""
```

## Best Practices

### Performance Tips

- **Order rules by cost**: Run fast rules (required fields) before slow rules (regex, schema)
- **Short-circuit**: Stop at first ERROR if you want to fail fast
- **Cache rule results**: If validating same data multiple times, cache
- **Batch validate**: When validating many items, run in parallel

### Severity Strategy

- **ERROR**: Use for hard constraints (required fields, hard limits)
- **WARNING**: Use for style/preference (too short, missing emoji)
- **INFO**: Use for metrics only (sentiment score, reading level)

### Common Pitfalls

**Silent failures**: Don't catch and ignore validation errors. Log them.

**Inflexible rules**: Make rules configurable so they work for multiple use cases.

**Cascading errors**: When one field is invalid, don't report errors on dependent fields.

**No repair path**: Always provide repair suggestions. Users should know how to fix issues.

**Overly strict**: Validate essentials, not formatting preferences. Let users choose style.

### When NOT to Use

- **Type checking**: Use type hints and mypy instead
- **Linting**: Use linters for code style
- **Parsing**: Use parsers for syntax validation
- **Authorization**: Use authentication/permissions instead

### Validation Policy as Code

```python
VALIDATION_POLICIES = {
    "twitter": {
        "required_fields": ["body"],
        "max_length_body": 280,
        "max_hashtags": 5,
    },
    "linkedin": {
        "required_fields": ["title", "body"],
        "max_length_body": 3000,
        "max_hashtags": 20,
    },
    "blog": {
        "required_fields": ["title", "body"],
        "min_length_body": 500,
        "max_images": 10,
    }
}

def create_validator_from_policy(platform: str):
    policy = VALIDATION_POLICIES[platform]
    rules = [
        RequiredFieldsRule(policy["required_fields"]),
    ]
    if "max_length_body" in policy:
        rules.append(LengthRule("body", max=policy["max_length_body"]))
    if "min_length_body" in policy:
        rules.append(LengthRule("body", min=policy["min_length_body"]))
    return ValidationPipeline(rules)
```

### Testing Validation Rules

```python
import pytest

@pytest.mark.asyncio
async def test_required_fields_rule():
    rule = RequiredFieldsRule(["title", "body"])

    # Should fail
    result = await rule.validate({"title": "Post"})
    assert result is not None
    assert "body" in result.message

    # Should pass
    result = await rule.validate({"title": "Post", "body": "Content"})
    assert result is None

@pytest.mark.asyncio
async def test_length_rule_with_repair():
    rule = LengthRule("body", max_length=10)
    result = await rule.validate({"body": "This is too long"})
    assert result.repair_suggestion is not None
```
