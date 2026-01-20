# CEMAF Comprehensive Cleanup Plan

**Date**: 2026-01-19
**Branch**: drchinca/cleanup
**Status**: In Progress

---

## Executive Summary

Comprehensive analysis of the CEMAF codebase identified **8 major categories** of cleanup opportunities:

1. **Dead Code** - 4 concrete issues
2. **Architectural Inconsistencies** - 2 major issues (ABC/Protocol confusion, Protocol duplication)
3. **Incomplete Implementations** - 3 silent exception handlers
4. **Code Quality** - 6 files >500 lines, magic numbers
5. **Duplications** - NoOp patterns, factory patterns
6. **Documentation** - Large commented examples in code
7. **Testing Gaps** - Some modules lack comprehensive tests
8. **Strengths** - Strong typing, immutability, no circular imports ✅

---

## Phase 1: Critical Fixes (Do Now)

### 1.1 ABC vs Protocol Documentation (CRITICAL)

**Issue**: Documentation says ABCs are "deprecated" but they're the primary pattern
**Impact**: Confuses developers about which to use

**Files to Update**:
- `src/cemaf/tools/protocols.py` - Line 173
- `src/cemaf/agents/protocols.py` - Line 119
- `src/cemaf/skills/protocols.py` - Line 148
- `src/cemaf/memory/protocols.py` - Line 142

**Action**:
```python
# Current (confusing):
"""
See Also:
    - cemaf.tools.base.Tool (deprecated ABC, use this protocol instead)
"""

# Change to:
"""
See Also:
    - cemaf.tools.base.Tool - ABC base class (recommended for most use cases)
    - This Protocol - For advanced structural typing without inheritance

Usage Guide:
    - Use ABC when you want helper methods and clear inheritance
    - Use Protocol when you need duck typing or wrapping existing objects
    - Function signatures should use Protocol for maximum flexibility
"""
```

**Status**: ⏳ Pending

---

### 1.2 Remove Dead Code in Retrieval Factories

**Issue**: 50 lines of commented TODO stubs for unimplemented vector stores
**File**: `src/cemaf/retrieval/factories.py`
**Lines**: 148-197

**Action**: Remove commented code blocks for:
- Pinecone integration
- Qdrant integration
- Weaviate integration
- Chroma integration
- PGVector integration
- FAISS integration

**Reasoning**: If not implemented, don't clutter the code. Document as extension points in docstring instead.

**Status**: ⏳ Pending

---

### 1.3 Fix Unreachable Dead Code

**Issue**: Unreachable `...` after return statement
**File**: `src/cemaf/memory/base.py`
**Line**: 191

```python
# Current:
async def cleanup_expired(self) -> int:
    return 0
    ...  # Unreachable!

# Fix:
async def cleanup_expired(self) -> int:
    """Base implementation returns 0 (no expired items)."""
    return 0
```

**Status**: ⏳ Pending

---

### 1.4 Fix Silent Exception Swallowing

**Issue**: Exceptions silently swallowed with no logging

**File 1**: `src/cemaf/moderation/pipeline.py` - Line 397
```python
# Current:
except Exception:
    pass

# Fix:
except Exception as e:
    logger.warning(f"Moderation pipeline error: {e}", exc_info=True)
```

**File 2**: `src/cemaf/config/loader.py` - Lines 100, 106
```python
# Current:
except FileNotFoundError:
    pass
except Exception:
    pass

# Fix:
except FileNotFoundError:
    logger.debug(f"Config file not found: {config_path}")
except Exception as e:
    logger.warning(f"Failed to load config: {e}", exc_info=True)
```

**Status**: ⏳ Pending

---

## Phase 2: Protocol Consolidation (Important)

### 2.1 Consolidate Duplicate Protocol Definitions

**Issue**: Protocols defined in both implementation and protocol files

**Duplicates Found**:

1. **ContextSelectionAlgorithm**:
   - `src/cemaf/context/algorithm.py` - Line 56
   - `src/cemaf/context/protocols.py` - Line 94

2. **ContextCompiler**:
   - `src/cemaf/context/compiler.py` - Line 131
   - `src/cemaf/context/protocols.py` - Line 42

**Action**:
- Keep protocol definitions ONLY in `*_protocols.py` files
- Import from protocols in implementation files
- Update all references

**Example**:
```python
# src/cemaf/context/protocols.py - Single source of truth
@runtime_checkable
class ContextSelectionAlgorithm(Protocol):
    def select(...) -> ...: ...

# src/cemaf/context/algorithm.py - Import from protocols
from cemaf.context.protocols import ContextSelectionAlgorithm

class GreedyAlgorithm:  # Implements protocol via duck typing
    def select(...) -> ...: ...
```

**Status**: ⏳ Pending

---

## Phase 3: Code Quality Improvements

### 3.1 Extract Magic Numbers to Constants

**File**: `src/cemaf/context/compiler.py` - Line 99

```python
# Current:
def __init__(self, chars_per_token: float = 4.0) -> None:

# Fix - add module-level constant:
DEFAULT_CHARS_PER_TOKEN = 4.0

def __init__(self, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> None:
```

**Status**: ⏳ Pending

---

### 3.2 Add Deprecation Warnings for Aliases

**File**: `src/cemaf/tools/base.py` - Lines 174-175

```python
# Current:
tool_decorator = tool

# Fix:
import warnings

def tool_decorator(*args, **kwargs):
    """Deprecated: Use @tool instead."""
    warnings.warn(
        "tool_decorator is deprecated, use @tool instead",
        DeprecationWarning,
        stacklevel=2
    )
    return tool(*args, **kwargs)
```

**Status**: ⏳ Pending

---

### 3.3 Refactor Large Files (>600 lines)

**Candidates for Splitting**:

1. **`src/cemaf/mcp/adapter.py`** - 771 lines
   - Consider splitting into:
     - `mcp/adapter/core.py` - Core adapter logic
     - `mcp/adapter/tools.py` - Tool integration
     - `mcp/adapter/resources.py` - Resource handling

2. **`src/cemaf/orchestration/executor.py`** - 726 lines
   - Consider splitting into:
     - `orchestration/executor/core.py` - Core execution
     - `orchestration/executor/context.py` - Context management
     - `orchestration/executor/hooks.py` - Hook handling

3. **`src/cemaf/blueprint/entities.py`** - 611 lines
   - Consider splitting by entity type

**Status**: 💭 Design discussion needed

---

## Phase 4: Documentation Cleanup

### 4.1 Move Large Commented Examples

**Issue**: 90+ lines of commented examples in code files

**Files**:
- `src/cemaf/tools/factories.py` - Lines 17-107
- `src/cemaf/skills/factories.py` - Similar

**Action**: Move to:
- `docs/examples/custom_tools.md`
- `examples/custom_tools/`

**Status**: ⏳ Pending

---

### 4.2 Standardize Docstrings

**Action**: Ensure all public APIs have:
- One-line summary
- Args description
- Returns description
- Example usage (for complex APIs)

**Priority Modules**:
- `generation/` - 545 lines but minimal docs
- `mcp/adapter.py` - 771 lines, needs better docs
- `orchestration/executor.py` - 726 lines

**Status**: ⏳ Pending

---

## Phase 5: Testing Improvements

### 5.1 Add Missing Test Coverage

**Modules with Limited Tests**:
- `generation/protocols.py` - 545 lines
- `blueprint/entities.py` - 611 lines
- `mcp/adapter.py` - 771 lines (needs integration tests)

**Action**: Add comprehensive unit tests

**Status**: 💭 Design discussion needed

---

### 5.2 Create Shared NoOp Utilities

**Issue**: NoOp pattern duplicated across modules

**Current**:
- `observability/simple.py` - NoOpSpan, NoOpTracer, NoOpMetrics
- Similar patterns in other mock modules

**Action**: Create `cemaf.testing.noop` module with:
- `NoOpBase` class
- Standard NoOp implementations
- Reuse across all test modules

**Status**: ⏳ Pending

---

## Architectural Strengths (Keep Doing)

### What's Working Well ✅

1. **Strong Type Hints**: Comprehensive type annotations throughout
2. **Immutability**: Consistent use of `frozen=True` dataclasses and Pydantic `frozen` config
3. **Protocol-First Design**: Runtime checkable protocols for extensibility
4. **No Circular Imports**: Clean module dependency graph
5. **No TYPE_CHECKING**: Follows global rule of direct imports
6. **Separation of Concerns**: Clear module boundaries

**Action**: Document these patterns in architecture guide

---

## Implementation Checklist

### High Priority (This Week)

- [ ] Fix ABC vs Protocol documentation (1.1)
- [ ] Remove dead code in retrieval factories (1.2)
- [ ] Fix unreachable code in memory/base.py (1.3)
- [ ] Fix silent exception handlers (1.4)

### Medium Priority (Next 2 Weeks)

- [ ] Consolidate duplicate protocols (2.1)
- [ ] Extract magic numbers (3.1)
- [ ] Add deprecation warnings (3.2)
- [ ] Move commented examples to docs (4.1)
- [ ] Create shared NoOp utilities (5.2)

### Low Priority (Future)

- [ ] Refactor large files (3.3) - Needs design discussion
- [ ] Standardize docstrings (4.2)
- [ ] Add missing test coverage (5.1)

---

## Metrics

### Before Cleanup
- Files >500 lines: 6 files
- Commented dead code: ~50 lines
- Protocol duplications: 2 pairs
- Silent exception handlers: 3 locations
- Unreachable code: 1 location

### After Cleanup (Target)
- Files >500 lines: TBD (design decision)
- Commented dead code: 0 lines
- Protocol duplications: 0 pairs
- Silent exception handlers: 0 (all logged)
- Unreachable code: 0

---

## Risk Assessment

### Low Risk Changes
✅ Remove commented dead code
✅ Fix unreachable ellipsis
✅ Add logging to exception handlers
✅ Extract magic numbers to constants
✅ Update documentation

### Medium Risk Changes
⚠️ Consolidate protocol definitions (test carefully)
⚠️ Add deprecation warnings (notify users)
⚠️ Create shared NoOp utilities (update all tests)

### High Risk Changes
🚨 Refactor large files (breaking change potential)
🚨 Protocol migration strategy (affects users)

---

## Next Steps

1. **Create PR for Phase 1** - High priority fixes
2. **Get review on Protocol consolidation** - Medium risk change
3. **Design discussion on large file refactoring** - High risk change
4. **Document architecture patterns** - Preserve strengths

---

## Related Documents

- [CLEANUP_ANALYSIS.md](./CLEANUP_ANALYSIS.md) - Original analysis
- [ARCHITECTURE_DECISION.md](./ARCHITECTURE_DECISION.md) - ABC vs Protocol decision
- [tests/unit/architecture/test_tool_patterns.py](./tests/unit/architecture/test_tool_patterns.py) - Pattern validation tests
