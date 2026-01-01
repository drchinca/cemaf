# Validation

Validation rules and pipelines for data validation.

## Validation Architecture

```mermaid
flowchart TB
    subgraph Rules
        LENGTH[LengthRule<br/>Min/max length]
        REGEX[RegexRule<br/>Pattern matching]
        RANGE[RangeRule<br/>Numeric bounds]
        CUSTOM[CustomRule<br/>User-defined]
    end

    subgraph Pipeline
        PIPE[ValidationPipeline<br/>Rule chain]
        INPUT[Input Data]
        OUTPUT[ValidationResult]
    end

    LENGTH --> PIPE
    REGEX --> PIPE
    RANGE --> PIPE
    CUSTOM --> PIPE
    INPUT --> PIPE
    PIPE --> OUTPUT
```

## Validation Flow

```mermaid
sequenceDiagram
    participant Caller
    participant Pipeline as ValidationPipeline
    participant Rule1 as LengthRule
    participant Rule2 as RegexRule
    participant Result as ValidationResult

    Caller->>Pipeline: validate(data)
    Pipeline->>Rule1: validate(data)
    Rule1-->>Pipeline: Pass

    Pipeline->>Rule2: validate(data)

    alt All rules pass
        Rule2-->>Pipeline: Pass
        Pipeline-->>Caller: ValidationResult(valid=True)
    else Any rule fails
        Rule2-->>Pipeline: Fail(error)
        Pipeline-->>Caller: ValidationResult(valid=False, errors)
    end
```

## Validation Pipeline

```python
from cemaf.validation.pipeline import ValidationPipeline
from cemaf.validation.rules import LengthRule, RegexRule

pipeline = ValidationPipeline() \
    .add_rule(LengthRule(min_length=5, max_length=100)) \
    .add_rule(RegexRule(pattern=r"^[a-z]+$"))

result = pipeline.validate("teststring")
```
