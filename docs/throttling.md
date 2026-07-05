# Resource Guards And Throttling

Status: not shipped in CEMAF.

CEMAF does not currently provide a `cemaf.throttling` package, resource circuit
breaker, context pager, CPU throttler, thermal manager, memory guard, disk
throttler, adaptive executor, or resource monitor. Older drafts of this page
described those APIs as if they existed; they do not.

## Current Guidance

Use shipped CEMAF primitives for the parts the framework actually owns:

- Use [Resilience](resilience.md) for retry, circuit breaking, rate limiting,
  and timeout policies around external calls.
- Use [Context](context.md), `TokenBudget`, and context selection primitives for
  token and context-size limits.
- Use [Observability](observability.md) and [Events](events.md) to report
  application-owned resource health.
- Put host CPU, memory, disk, and thermal policy in the consuming deployment
  layer, then inject any resulting gates through `RuntimeServices` or
  interceptors.

## Design Boundary

Reusable throttling belongs in CEMAF only when it is protocol-shaped and proven
with integration tests across DAG execution, event emission, and replay. Host
resource monitors, device-specific thermal paths, and storage spillover policy
are deployment concerns until that protocol exists.
