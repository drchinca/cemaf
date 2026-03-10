# CEMAF Project Instructions

## Testing Discipline

**CRITICAL**: Every feature requires THREE levels of testing:

1. **Contract tests (TDD)** — Define interfaces/protocols first, write 2-3 contract tests before implementing
2. **Unit tests** — Test each module in isolation with mocks/fakes
3. **Integration tests** — Test actual wiring between modules to verify they work together end-to-end

### Integration Testing Rules

- Unit tests alone are insufficient. If module A produces output that module B consumes, there MUST be an integration test that wires A → B with real implementations (not mocks)
- Integration tests live in `tests/integration/` mirroring the module pairs they test (e.g., `tests/integration/test_memory_context.py`)
- When adding a bridge, adapter, or cross-module factory, the PR is NOT complete until integration tests prove the seam works
- A `to_*()` bridge method without a test that actually feeds its output into the target system is a dead-end seam, not an integration

### Examples of Required Integration Tests

| Feature | Integration Test |
|---------|-----------------|
| SemanticMemoryStore | Memory store + VectorStore + EmbeddingProvider wired together, store and search round-trip |
| CompactedMemory.to_context_source() | Compact memory items → feed into ContextCompiler → verify compiled output |
| SessionManager lifecycle | Bootstrap → ingest → compact → verify context sources are usable |
| MemoryManager + EventBus | Remember items → verify events actually published and receivable |
