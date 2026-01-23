# Moderation Module - Extended Documentation

## Overview

The moderation module provides content safety gates and compliance checking for generated content, supporting pre-flight (before generation), post-flight (before publishing), and custom moderation rules.

**What it does**: Implements pluggable moderation gates that evaluate content against business rules, safety policies, and compliance requirements. Supports keyword filtering, PII detection, pattern matching, length validation, and composite rules. Can block, flag, or repair content based on violation severity.

**Key use cases**:
- Prevent harmful, hateful, or unsafe content from being published
- Enforce brand guidelines and tone requirements
- Comply with data protection regulations (GDPR, CCPA)
- Flag sensitive content for human review
- Automatically repair simple violations (truncate, remove PII)
- A/B test different moderation policies

**When to use vs. alternatives**: Use moderation before publishing content to external platforms. Use it to enforce legal/safety requirements. Don't use for general validation (use validation module) or runtime safety (use resilience module for circuit breakers).

## Core Concepts

### Moderation Architecture

The module has three layers:

**Rules**: Individual validation logic (KeywordRule, PIIRule, PatternRule, LengthRule). Each rule checks one thing and returns a ModerationViolation if it fails.

**Gates**: Combine multiple rules with different severities. PreFlightGate runs before generation, PostFlightGate runs before publishing. CompositeGate combines multiple gates.

**Pipeline**: Orchestrates gates and aggregates results. Determines overall safety status, collects all violations, and applies repair strategies.

### Violation Severity

Each violation has a severity level controlling behavior:

**BLOCKING**: Immediately fails the entire content. No content with BLOCKING violations should ever be published.

**WARNING**: Noted but permits continuation. Human review recommended. Useful for style issues or controversial topics.

**INFO**: Purely informational. Doesn't affect publication decisions. Used for metrics and analytics.

### Gate Types

**PreFlightGate**: Runs before generation. Validates inputs, briefs, and parameters. Catches policy issues early, saving compute.

**PostFlightGate**: Runs before publishing. Validates complete generated content. Catches unsafe outputs before they reach users.

**CompositeGate**: Combines multiple gates. Runs all, aggregates violations. Useful when you have multiple independent safety concerns.

## Usage Examples

### Basic Content Safety Check

```python
from cemaf.moderation import ModerationPipeline, KeywordRule, LengthRule
from cemaf.moderation.protocols import ModerationSeverity

# Create pipeline with safety rules
moderator = ModerationPipeline([
    KeywordRule(
        forbidden_keywords=["hate", "violent", "explicit"],
        severity=ModerationSeverity.BLOCKING
    ),
    LengthRule(
        max_length=280,
        severity=ModerationSeverity.WARNING
    ),
])

# Moderate content before publishing
content = "This is a great new product launch!"
result = await moderator.moderate(content)

if result.safe:
    print(f"Content is safe. {len(result.violations)} warnings")
    # Publish content
else:
    print(f"Content blocked due to violations:")
    for v in result.violations:
        print(f"  - {v.rule}: {v.message} ({v.severity})")
```

### PII Detection and Handling

```python
from cemaf.moderation import PIIRule, ModerationPipeline
from cemaf.moderation.protocols import ModerationSeverity

# Detect personally identifiable information
moderator = ModerationPipeline([
    PIIRule(
        detect_email=True,
        detect_phone=True,
        detect_ssn=True,
        detect_credit_card=True,
        severity=ModerationSeverity.BLOCKING  # PII must be removed
    )
])

content = "Contact John at john@example.com or 555-123-4567"
result = await moderator.moderate(content)

if not result.safe:
    for v in result.violations:
        if v.repair_suggestion:
            print(f"Repair: {v.repair_suggestion}")
            # Apply repair: Remove email and phone

    # Repair and re-check
    repaired = "Contact John or reach out to our support team"
    result = await moderator.moderate(repaired)
    assert result.safe
```

### Pre-flight Validation Before Generation

```python
from cemaf.moderation import PreFlightGate, KeywordRule, PatternRule

# Validate input brief before expensive generation
gate = PreFlightGate([
    KeywordRule(
        forbidden_keywords=["banned_topic"],
        severity=ModerationSeverity.BLOCKING
    ),
    PatternRule(
        forbidden_patterns=[r".*illegal.*"],
        severity=ModerationSeverity.BLOCKING
    ),
])

brief = "Create social content about our new product"
result = await gate.check(brief)

if result.safe:
    # Safe to proceed with generation
    generated = await generate_content(brief)
else:
    # Stop before wasting resources
    print(f"Brief violates policy: {result.violations[0].message}")
```

### Post-flight Validation Before Publishing

```python
from cemaf.moderation import PostFlightGate, LengthRule, PatternRule

# Validate complete generated content before publishing
gate = PostFlightGate([
    LengthRule(
        min_length=10,
        max_length=280,
        severity=ModerationSeverity.WARNING
    ),
    PatternRule(
        forbidden_patterns=[r"@\w+\s+is\s+\w+\s+scam"],
        severity=ModerationSeverity.BLOCKING
    ),
])

generated_post = "Check out our new AI features - they're amazing!"
result = await gate.check(generated_post)

if result.safe:
    # Safe to publish
    await publish(generated_post)
else:
    # Queue for human review
    await review_queue.add(generated_post, violations=result.violations)
```

### Composite Moderation Pipeline

```python
from cemaf.moderation import (
    ModerationPipeline,
    PreFlightGate,
    PostFlightGate,
    CompositeGate,
    KeywordRule,
    PIIRule,
    LengthRule,
)

# Create comprehensive safety pipeline
preflight = PreFlightGate([
    KeywordRule(forbidden_keywords=["banned_topics"],
                severity=ModerationSeverity.BLOCKING),
])

postflight = PostFlightGate([
    PIIRule(detect_email=True, severity=ModerationSeverity.BLOCKING),
    LengthRule(max_length=280, severity=ModerationSeverity.WARNING),
    KeywordRule(forbidden_keywords=["hate", "violence"],
                severity=ModerationSeverity.BLOCKING),
])

composite = CompositeGate([preflight, postflight])

# Single call checks both
brief = "Create a post about..."
result = await composite.check(brief)

# All violations collected
print(f"Total violations: {len(result.violations)}")
for v in result.violations:
    print(f"  {v.rule}: {v.message}")
```

### Custom Moderation Rules

```python
from cemaf.moderation.protocols import ModerationRule, ModerationViolation, ModerationSeverity
from typing import Protocol

class BrandGuidelinesRule(ModerationRule):
    """Custom rule enforcing brand guidelines."""

    def __init__(self, brand_tone: str, severity: ModerationSeverity):
        self.brand_tone = brand_tone
        self.severity = severity

    async def check(self, content: str) -> ModerationViolation | None:
        """Check if content matches brand tone."""
        if self.brand_tone == "professional":
            # Professional tone shouldn't have emojis
            if any(ord(c) > 127 for c in content):
                return ModerationViolation(
                    rule="brand_tone",
                    message="Professional content should not contain emojis",
                    severity=self.severity,
                    repair_suggestion="Remove emojis: " + content.replace("😀", "")
                )
        return None

# Use custom rule
moderator = ModerationPipeline([
    BrandGuidelinesRule("professional", ModerationSeverity.WARNING)
])

content = "Excited to announce our new features! 🎉🎉"
result = await moderator.moderate(content)
if not result.safe:
    print(result.violations[0].repair_suggestion)
```

### Handling Multiple Content Types

```python
from cemaf.moderation import ModerationPipeline, LengthRule, PatternRule

# Different rules for different platforms
twitter_rules = [
    LengthRule(max_length=280, severity=ModerationSeverity.BLOCKING),
    PatternRule(forbidden_patterns=[r"@.*is.*scam"],
                severity=ModerationSeverity.BLOCKING),
]

linkedin_rules = [
    LengthRule(max_length=3000, severity=ModerationSeverity.BLOCKING),
    PatternRule(forbidden_patterns=[r"crypto.*guaranteed.*returns"],
                severity=ModerationSeverity.BLOCKING),
]

tiktok_rules = [
    LengthRule(max_length=2200, severity=ModerationSeverity.WARNING),
]

moderators = {
    "twitter": ModerationPipeline(twitter_rules),
    "linkedin": ModerationPipeline(linkedin_rules),
    "tiktok": ModerationPipeline(tiktok_rules),
}

# Use platform-specific moderator
content = "Check out our product..."
platform = "twitter"
result = await moderators[platform].moderate(content)
```

### Common Mistake: Ignoring Repair Suggestions

```python
# ❌ WRONG - Discard content with warnings
result = await moderator.moderate(content)
if not result.safe:
    # Just skip it
    return None

# ✅ CORRECT - Try repair suggestions first
result = await moderator.moderate(content)
if not result.safe:
    # Collect repair suggestions
    repaired = content
    for v in result.violations:
        if v.repair_suggestion and v.severity != ModerationSeverity.BLOCKING:
            repaired = v.repair_suggestion

    # Re-check repaired version
    result = await moderator.moderate(repaired)
    if result.safe:
        return repaired
    else:
        # Only reject if still has BLOCKING violations
        return None if has_blocking(result) else repaired
```

## Integration

### With Content Publishing Pipeline

```python
from cemaf.moderation import ModerationPipeline
from cemaf.persistence.entities import ContentStatus

# Gate content state transitions
async def approve_content(content_item, moderator):
    """Only approve content that passes moderation."""
    result = await moderator.moderate(content_item.body)

    if result.safe:
        return content_item.with_status(ContentStatus.APPROVED)
    else:
        # Track why it failed
        return content_item.model_copy(update={
            "status": ContentStatus.FAILED,
            "metadata": {
                **content_item.metadata,
                "moderation_violations": [
                    {
                        "rule": v.rule,
                        "message": v.message,
                        "severity": v.severity.value
                    }
                    for v in result.violations
                ]
            }
        })
```

### With Generation Module

```python
from cemaf.generation.protocols import ImageGenerator
from cemaf.moderation import ModerationPipeline

class SafeImageGenerator:
    """Image generator with moderation checks."""

    def __init__(self, generator: ImageGenerator, moderator: ModerationPipeline):
        self.generator = generator
        self.moderator = moderator

    async def generate_safe(self, prompt: str):
        """Generate image only if prompt passes safety checks."""
        # Pre-flight check
        preflight_result = await self.moderator.moderate(prompt)
        if not preflight_result.safe:
            raise ValueError(f"Unsafe prompt: {preflight_result.violations}")

        # Generate
        image = await self.generator.generate(prompt)

        # Could post-flight check image description if available
        return image
```

### With Validation Module

```python
from cemaf.validation import ValidationPipeline, Rule
from cemaf.moderation import ModerationPipeline

# Combine safety and business rules
class ModerationRule(Rule):
    """Validation rule based on moderation checks."""

    def __init__(self, moderator: ModerationPipeline):
        self.moderator = moderator

    async def validate(self, value: str):
        result = await self.moderator.moderate(value)
        if not result.safe:
            return ValidationError(
                message=f"Content failed safety checks",
                details=[(v.rule, v.message) for v in result.violations]
            )
        return None

# Use in validation pipeline
moderator = ModerationPipeline([...])
validator = ValidationPipeline([
    SchemaRule(...),
    LengthRule(...),
    ModerationRule(moderator),  # Safety check
])
```

### With Events Module

```python
from cemaf.events import EventBus

class ModerationEventPublisher:
    """Publish moderation results as events for alerting."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def moderate_and_notify(self, content: str, moderator):
        result = await moderator.moderate(content)

        if not result.safe:
            # Publish event for monitoring
            await self.event_bus.publish({
                "type": "content.moderation.violation",
                "severity": "blocking" if any(
                    v.severity.value == "blocking"
                    for v in result.violations
                ) else "warning",
                "violations": len(result.violations),
                "content_preview": content[:100]
            })

        return result
```

## API Reference

### ModerationSeverity Enum

```python
class ModerationSeverity(str, Enum):
    BLOCKING = "blocking"    # Content must not pass
    WARNING = "warning"      # Content is flagged but can continue
    INFO = "info"            # Informational only
```

### ModerationViolation Dataclass

```python
@dataclass
class ModerationViolation:
    rule: str                               # Rule that triggered
    message: str                            # Human-readable message
    severity: ModerationSeverity           # How serious is it
    context: str = ""                      # Where in content it occurred
    repair_suggestion: str | None = None   # How to fix it
```

### ModerationResult Dataclass

```python
@dataclass
class ModerationResult:
    safe: bool                              # Overall safety verdict
    violations: tuple[ModerationViolation, ...] = ()
    blocked_reason: str | None = None      # If safe=False, why blocked

    def has_blocking(self) -> bool:
        """Whether any violations are BLOCKING severity."""
        return any(
            v.severity == ModerationSeverity.BLOCKING
            for v in self.violations
        )
```

### Rule Implementations

```python
class KeywordRule(ModerationRule):
    """Block if content contains forbidden keywords."""
    def __init__(
        self,
        forbidden_keywords: list[str],
        case_sensitive: bool = False,
        whole_word: bool = False,
        severity: ModerationSeverity = BLOCKING
    ): ...

class PIIRule(ModerationRule):
    """Detect and block PII."""
    def __init__(
        self,
        detect_email: bool = True,
        detect_phone: bool = True,
        detect_ssn: bool = True,
        detect_credit_card: bool = True,
        severity: ModerationSeverity = BLOCKING
    ): ...

class PatternRule(ModerationRule):
    """Block if content matches regex patterns."""
    def __init__(
        self,
        forbidden_patterns: list[str],  # Regex patterns
        severity: ModerationSeverity = BLOCKING
    ): ...

class LengthRule(ModerationRule):
    """Enforce content length limits."""
    def __init__(
        self,
        min_length: int | None = None,
        max_length: int | None = None,
        severity: ModerationSeverity = WARNING
    ): ...
```

### Gates

```python
class PreFlightGate:
    """Moderation gate that runs before generation."""
    def __init__(self, rules: list[ModerationRule]): ...
    async def check(self, inputs: dict | str) -> ModerationResult: ...

class PostFlightGate:
    """Moderation gate that runs before publishing."""
    def __init__(self, rules: list[ModerationRule]): ...
    async def check(self, content: str) -> ModerationResult: ...

class CompositeGate:
    """Combines multiple gates."""
    def __init__(self, gates: list[PreFlightGate | PostFlightGate]): ...
    async def check(self, *args, **kwargs) -> ModerationResult: ...
```

### Pipeline

```python
class ModerationPipeline:
    """Orchestrates rules and gates."""
    def __init__(self, rules: list[ModerationRule]): ...
    async def moderate(self, content: str) -> ModerationResult: ...
```

## Best Practices

### Performance Tips

- **Order rules by speed**: Put fast rules (keyword) before slow rules (ML-based)
- **Cache violation checks**: If checking same content multiple times, cache results
- **Use PreFlightGate early**: Stop early before expensive generation
- **Batch moderation**: When checking multiple contents, run in parallel:
  ```python
  results = await asyncio.gather(
      moderator.moderate(content1),
      moderator.moderate(content2),
      moderator.moderate(content3)
  )
  ```

### Severity Strategy

- **BLOCKING**: Only for legal/safety imperatives (PII, hate speech, misinformation)
- **WARNING**: For brand/quality issues (tone, length, style)
- **INFO**: For metrics only (mentions, sentiment, tone)

Avoid making everything BLOCKING or nothing will ever publish.

### Common Pitfalls

**Ignoring repair suggestions**: Many violations can be auto-repaired (trim length, remove PII). Always try repair before rejecting.

**Over-moderation**: Overly strict rules will block legitimate content. Test rules with production content samples first.

**Missing context**: When flagging content, save which rule failed and why. Helps debugging.

**Not updating rules**: As platforms change, safety concerns evolve. Review and update rules quarterly.

**Async safety**: Moderation can be slow (ML models, API calls). Always await properly. Never block on moderation synchronously.

### When NOT to Use

- **Real-time filtering**: For live chat or user input, this is too slow
- **Spam detection**: Use dedicated spam filters (module not included)
- **Fact-checking**: Module detects patterns, not truth
- **Legal compliance**: Don't rely on automated moderation for legal compliance. Combine with human review.

### Policy as Code

Document moderation policies in configuration:

```python
MODERATION_POLICIES = {
    "twitter": {
        "max_length": 280,
        "forbidden_keywords": ["hate", "violence"],
        "detect_pii": True,
        "brand_tone": "conversational",
    },
    "linkedin": {
        "max_length": 3000,
        "forbidden_keywords": ["crypto_spam"],
        "detect_pii": True,
        "brand_tone": "professional",
    }
}

# Load rules from policy
def create_moderator(platform: str):
    policy = MODERATION_POLICIES[platform]
    rules = [
        LengthRule(max_length=policy["max_length"]),
        KeywordRule(forbidden_keywords=policy["forbidden_keywords"]),
        PIIRule() if policy["detect_pii"] else None,
    ]
    return ModerationPipeline([r for r in rules if r])
```

### Testing Rules

```python
import pytest

@pytest.mark.asyncio
async def test_keyword_rule_blocks_forbidden():
    rule = KeywordRule(forbidden_keywords=["hate"])

    # Should block
    v = await rule.check("I hate this")
    assert v is not None

    # Should pass
    v = await rule.check("I love this")
    assert v is None

@pytest.mark.asyncio
async def test_pii_rule_detects_email():
    rule = PIIRule(detect_email=True)

    v = await rule.check("Contact john@example.com")
    assert v is not None
    assert "email" in v.message.lower()
```
