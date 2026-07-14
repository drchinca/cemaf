# Offline Operation

Status: not shipped in CEMAF.

CEMAF does not currently provide a `cemaf.offline` package, offline queue,
offline run logger, local-LLM fallback wrapper, connectivity monitor, bandwidth
manager, or offline tool policy enum. Older drafts of this page described those
APIs as if they existed; they do not.

## Current Guidance

Applications can still run CEMAF in constrained or intermittently connected
environments by composing shipped primitives:

- Use a local or application-owned queue for store-and-forward behavior.
- Persist memory with `JsonFileMemoryStore`, `SqliteMemoryStore`, or a custom
  `MemoryStore`.
- Persist run visibility through `RunLogger` implementations and replay files.
- Use `LLMClient` adapters, `ResilientLLMClient`, and application-level routing
  for local/cloud fallback.
- Inject those choices through `RuntimeServices` and the composition root.

## Related Shipped Primitives

- [LLM](llm.md)
- [Memory](memory.md)
- [Observability](observability.md)
- [Replay](replay.md)
- [Resilience](resilience.md)
- [Runtime service composition](patterns.md)

If offline support becomes reusable framework behavior, it should start as a
protocol and integration spec, not as application-specific queue code inside the
framework core.
