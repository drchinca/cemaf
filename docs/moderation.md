# Content Moderation

The Moderation module provides content safety and guardrails through pre-flight and post-flight checks. It ensures compliance, detects PII, enforces content policies, and integrates with CEMAF's observability stack.

## Overview

Moderation in CEMAF follows a pipeline pattern:

1. **Pre-Flight Gate**: Checks content BEFORE processing (inputs, prompts)
2. **Post-Flight Gate**: Checks content AFTER processing (outputs, responses)
3. **Moderation Pipeline**: Chains gates together with event integration

## Core Components

### ModerationPipeline

The `ModerationPipeline` provides a unified interface for content moderation:

```python
from cemaf.moderation import ModerationPipeline, PreFlightGate, PostFlightGate
from cemaf.moderation.rules import KeywordRule, LengthRule, PIIRule

# Create gates
pre_gate = PreFlightGate([KeywordRule(blocked_words=("spam",)), PIIRule()])
post_gate = PostFlightGate([LengthRule(max_length=4000)])

# Create pipeline
pipeline = ModerationPipeline(
    pre_flight=pre_gate,
    post_flight=post_gate,
    event_bus=my_event_bus,
)

# Check input
result = await pipeline.check_input(user_message)
if not result.allowed:
    raise ContentBlockedError(result.violations)

# Check output
result = await pipeline.check_output(llm_response)
if not result.allowed:
    # Handle blocked content
    pass
```

### PreFlightGate

Checks content before processing:

```python
from cemaf.moderation import PreFlightGate
from cemaf.moderation.rules import KeywordRule, PIIRule

gate = PreFlightGate(
    rules=[KeywordRule(blocked_words=("spam", "phishing")), PIIRule()],
    fail_fast=True,  # Stop on first error-level violation
)

result = await gate.check(user_input)
if not result.allowed:
    print(f"Blocked: {result.violations}")
```

### PostFlightGate

Checks content after processing:

```python
from cemaf.moderation import PostFlightGate
from cemaf.moderation.rules import LengthRule, PatternRule

gate = PostFlightGate(
    rules=[
        LengthRule(max_length=4000),
        PatternRule(
            pattern=r"\bmedical advice\b",
            violation_code="medical_advice",
            violation_message="Medical advice requires an explicit product policy",
        ),
    ],
    redact_on_violation=False,
)

result = await gate.check(llm_output)
```

## Moderation Rules

### KeywordRule

Blocks content containing specific keywords:

```python
from cemaf.moderation.rules import KeywordRule

rule = KeywordRule(
    blocked_words=("spam", "phishing", "malware"),
    severity="error",  # "error" or "warning"
    whole_word_only=True,
)
```

### PIIRule

Detects Personally Identifiable Information:

```python
from cemaf.moderation.rules import PIIRule

rule = PIIRule(
    detect_email=True,
    detect_phone=True,
    detect_ssn=True,
    detect_credit_card=True,
    severity="error",
)
```

### LengthRule

Checks minimum or maximum content length:

```python
from cemaf.moderation.rules import LengthRule

rule = LengthRule(
    min_length=10,
    max_length=4000,
    severity="warning",
)
```

### PatternRule

Blocks content that matches a custom regex pattern:

```python
from cemaf.moderation.rules import PatternRule

rule = PatternRule(
    pattern=r"\bmedical advice\b",
    violation_code="medical_advice",
    violation_message="Medical advice requires an explicit product policy",
    severity="error",
)
```

### Custom Rules

Create custom moderation rules:

```python
from cemaf.moderation import ModerationRule, ModerationResult, ModerationViolation

class CustomRule(ModerationRule):
    async def check(self, content: Any, context: Context | None = None) -> ModerationResult:
        violations = []

        # Custom logic
        if "forbidden_term" in str(content):
            violations.append(
                ModerationViolation(
                    rule_name="custom_rule",
                    severity="error",
                    message="Forbidden term detected",
                )
            )

        return ModerationResult(
            allowed=len(violations) == 0,
            violations=violations,
        )
```

## ModerationResult

The result of a moderation check:

```python
from cemaf.moderation import ModerationResult

result = ModerationResult(
    allowed=True,  # Whether content passed
    violations=[],  # List of violations
    metadata={},  # Additional metadata
)

# Properties
if result.allowed:
    # Content passed
    pass

for violation in result.violations:
    print(f"{violation.severity}: {violation.message}")
```

## ModerationViolation

Represents a single violation:

```python
from cemaf.moderation import ModerationViolation

violation = ModerationViolation(
    rule_name="keyword_rule",
    severity="error",  # "error" or "warning"
    message="Blocked keyword detected: spam",
    metadata={"keyword": "spam", "position": 42},
)
```

## Integration with Tools

Tools can use moderation pipelines:

```python
from cemaf.tools import Tool
from cemaf.moderation import ModerationPipeline

class WebSearchTool(Tool):
    def __init__(self, moderation_pipeline: ModerationPipeline | None = None):
        super().__init__(...)
        self._moderation = moderation_pipeline

    async def execute(self, query: str) -> Result[str]:
        # Pre-flight check
        if self._moderation:
            result = await self._moderation.check_input(query)
            if not result.allowed:
                return Result.failure("Query blocked by moderation")

        # Execute tool
        response = await self._search(query)

        # Post-flight check
        if self._moderation:
            result = await self._moderation.check_output(response)
            if not result.allowed:
                return Result.failure("Response blocked by moderation")

        return Result.success(response)
```

## Integration with LLM

Moderate LLM inputs and outputs:

```python
from cemaf.llm import LLMClient
from cemaf.moderation import ModerationPipeline

llm = LLMClient(...)
pipeline = ModerationPipeline(...)

# Moderate input
input_result = await pipeline.check_input(user_prompt)
if not input_result.allowed:
    raise ContentBlockedError(input_result.violations)

# Generate response
response = await llm.complete(user_prompt)

# Moderate output
output_result = await pipeline.check_output(response.content)
if not output_result.allowed:
    # Handle blocked output
    response = await llm.complete("Please provide a safe alternative response")
```

## Wrapped Execution

Use `wrap_execution` for automatic moderation:

```python
async def my_llm_call(content: str) -> str:
    return await llm.complete(content)

# Automatically checks input and output
mod_result, output = await pipeline.wrap_execution(
    content=user_message,
    executor=my_llm_call,
)

if not mod_result.allowed:
    # Handle moderation failure
    pass
```

## Event Integration

Moderation pipeline emits events:

```python
from cemaf.events import EventBus

event_bus = EventBus()
pipeline = ModerationPipeline(
    pre_flight=pre_gate,
    post_flight=post_gate,
    event_bus=event_bus,
)

# Events emitted:
# - moderation.check.started: When check begins
# - moderation.check.passed: When content passes
# - moderation.check.blocked: When content is blocked
# - moderation.violation.detected: When violation found
```

## Usage Patterns

### Pattern 1: Input Validation

```python
# Validate user input before processing
result = await pipeline.check_input(user_message)
if not result.allowed:
    return error_response(result.violations)
```

### Pattern 2: Output Filtering

```python
# Filter LLM outputs
result = await pipeline.check_output(llm_response)
if not result.allowed:
    # Regenerate or filter
    filtered_response = await filter_content(llm_response)
```

### Pattern 3: Wrapped Execution

```python
# Automatic moderation wrapper
mod_result, output = await pipeline.wrap_execution(
    content=input,
    executor=lambda x: llm.complete(x),
)
```

### Pattern 4: Multi-Stage Moderation

```python
# Different rules for different stages
pre_gate = PreFlightGate([KeywordRule(blocked_words=("spam",)), PIIRule()])
post_gate = PostFlightGate([LengthRule(max_length=4000)])

pipeline = ModerationPipeline(
    pre_flight=pre_gate,
    post_flight=post_gate,
)
```

## Best Practices

1. **Use pre-flight for inputs**: Check user inputs before processing
2. **Use post-flight for outputs**: Check LLM outputs before returning
3. **Fail fast for errors**: Stop on error-level violations
4. **Collect warnings**: Continue on warning-level violations
5. **Emit events**: Use EventBus for observability
6. **Customize rules**: Create domain-specific rules
7. **Test moderation**: Test with various content types
8. **Monitor violations**: Track violation patterns

## Testing

Use mock moderation components:

```python
from cemaf.moderation.mock import MockModerationPipeline

pipeline = MockModerationPipeline(always_allow=True)
result = await pipeline.check_input("test")
assert result.allowed
```

## Related Modules

- **Tools**: Tools can use moderation pipelines
- **LLM**: LLM inputs/outputs can be moderated
- **Events**: Moderation events emitted to EventBus
- **Validation**: Moderation rules complement validation rules
- **Observability**: Moderation events tracked in RunLogger
