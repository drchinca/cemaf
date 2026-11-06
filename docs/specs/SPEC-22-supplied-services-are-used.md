---
title: Supplied Runtime Services Are Used
spec_id: SPEC-22
status: Implemented
last_reviewed: 2026-11-06
owner: drchinca
parent: none
depends_on: []
---

# SPEC-22: Supplied Runtime Services Are Used

> A service handed to the composition root runs unless the caller explicitly
> turns it off. Supplying a safety service must never be a silent no-op.

## 1. Context

`ExecutorConfig` has three switches that gate services from `RuntimeServices`:
`enable_logging` and `enable_events` default to True, but `enable_moderation`
defaulted to False. So `create_executor(services=RuntimeServices(moderation_pipeline=p))`
built an executor that never moderated anything, with no warning. The same
default lived in `create_executor_config` and `create_dag_executor`. For a
content-safety control, "configured but off" is the worst failure mode: the
operator believes output is screened and it is not.

## 2. Interface Contract (MDE)

```python
class ExecutorConfig(BaseModel):
    enable_logging: bool = True
    enable_events: bool = True
    enable_moderation: bool = True      # was False

def create_executor_config(*, ..., enable_moderation: bool = True, ...) -> ExecutorConfig: ...
```

Setting `enable_moderation=False` still turns moderation off; a `None`
`moderation_pipeline` still means no moderation.

## 3. Invariants (DbC)

1. `WHEN a moderation pipeline is supplied and the config does not set enable_moderation=False, THE System SHALL moderate every node result.`
2. `IF enable_moderation=False, THEN THE System SHALL NOT moderate`, whatever pipeline is supplied.
3. `ExecutorConfig and create_executor_config SHALL share the same defaults.`

Budget: 3 invariants.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Supplied services are used

  Scenario: A supplied moderation pipeline moderates by default
    Given create_executor with RuntimeServices(moderation_pipeline=blocks "FORBIDDEN")
    And the default ExecutorConfig
    When an agent returns "FORBIDDEN draft"
    Then the node fails moderation and its output never reaches the context

  Scenario: Moderation can still be turned off explicitly
    Given the same services and ExecutorConfig(enable_moderation=False)
    When the agent returns "FORBIDDEN draft"
    Then the node succeeds
```

## 5. Out of Scope

- Removing the `enable_*` switches — consumers (`meridiansight`, `kyi`) set them
  explicitly and pin them in contract tests.
- Logging or events defaults (already True).

## 6. Dependencies

- `cemaf.orchestration.executor.ExecutorConfig`, `cemaf.bootstrap.create_executor`,
  `cemaf.orchestration.factories.create_executor_config`.

## 10. Test Coverage Update

- **Integration** (`tests/integration/test_runtime_services_composite.py`): both §4
  scenarios through `create_executor` with a real keyword moderation pipeline.
- **Unit** (`tests/unit/test_dag_executor.py`, `tests/unit/orchestration/test_factories.py`):
  the shared default.
