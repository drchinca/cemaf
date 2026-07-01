"""Context layer: the memory scope hierarchy (GLOBAL -> TENANT -> SESSION).

Use-case: a fact like "preferred tone" has a sensible default GLOBALLY, an
override per TENANT (org), and a per-conversation override at SESSION. CEMAF
layers these by scope so recall sees every layer, and a narrower scope can
override a broader default.

Best practice shown: don't build your own per-tenant/per-session dicts — store
the same key at different MemoryScopes and let recall walk the layers.

Usage:
    uv run python examples/context_layers/memory_scope_hierarchy.py
"""

import asyncio

from cemaf.core.enums import MemoryScope
from cemaf.memory.factories import create_memory_manager
from cemaf.memory.semantic import MemoryQuery


async def main() -> None:
    manager = create_memory_manager()

    # The SAME concept ("tone") layered at three scopes, broad to narrow.
    await manager.remember(
        MemoryScope.GLOBAL,
        "tone",
        {"value": "formal"},
        content_for_embedding="default writing tone is formal",
    )
    await manager.remember(
        MemoryScope.TENANT,
        "tone",
        {"value": "friendly"},
        content_for_embedding="tenant writing tone is friendly",
    )
    await manager.remember(
        MemoryScope.SESSION,
        "tone",
        {"value": "casual"},
        content_for_embedding="this session's writing tone is casual",
    )

    # Recall across the layer stack — every scope's value surfaces, narrow first.
    layered = await manager.recall(
        MemoryQuery(
            text="tone",
            scopes=(MemoryScope.SESSION, MemoryScope.TENANT, MemoryScope.GLOBAL),
            limit=5,
        )
    )

    # Resolution: the narrowest scope present wins (session overrides global).
    session = await manager.recall_by_key(MemoryScope.SESSION, "tone")
    global_default = await manager.recall_by_key(MemoryScope.GLOBAL, "tone")

    assert {r.item.scope for r in layered} == {
        MemoryScope.SESSION,
        MemoryScope.TENANT,
        MemoryScope.GLOBAL,
    }
    assert session is not None and session.value == {"value": "casual"}
    assert global_default is not None and global_default.value == {"value": "formal"}

    print("layered recall (narrow -> broad):")
    for result in layered:
        print(f"  {result.item.scope.value:<8} tone = {result.item.value['value']}")
    print(f"resolved for this session: {session.value['value']} (overrides global default)")


if __name__ == "__main__":
    asyncio.run(main())
