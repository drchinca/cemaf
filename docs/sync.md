# State Synchronization

Status: not shipped in CEMAF.

CEMAF does not currently provide a `cemaf.sync` package, CRDT runtime, vector
clock implementation, sync transport, or conflict-resolution service. Older
drafts of this page described those APIs as if they existed; they do not.

## Current Guidance

For production systems that need device-to-cloud or multi-writer state sync:

- Keep synchronization in the consuming application or an external service.
- Use CEMAF's existing `Context`, `ContextPatch`, `MemoryStore`, `RunLogger`,
  `EventBus`, and replay primitives as the local execution substrate.
- Represent sync outcomes as ordinary application events, memory updates, or
  context patches instead of depending on a CEMAF sync manager.
- Add a reusable CEMAF sync capability only after there is a concrete protocol,
  storage contract, and integration test that proves it composes with
  `RuntimeServices`.

## Related Shipped Primitives

- [Context](context.md)
- [Memory](memory.md)
- [Events](events.md)
- [Observability](observability.md)
- [Replay](replay.md)

For speculative distributed-state requirements, track them in a spec or design
proposal before adding public API examples.
