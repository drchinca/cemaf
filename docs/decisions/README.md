# Decision Log

This directory contains all major decisions made in CEMAF's development. We document decisions to:

1. **Build trust** through transparency
2. **Prevent rehashing** old discussions
3. **Onboard contributors** faster with context
4. **Learn** from what worked and what didn't

## Decision Format

Each decision follows this structure:

```markdown
# [Title of Decision]

**Date:** YYYY-MM-DD
**DRI:** @username (Directly Responsible Individual)
**Status:** Proposed | Adopted | Deprecated | Superseded
**Context:** Why we're making this decision
**Decision:** What we decided
**Why:** Reasoning and trade-offs
**Alternatives Considered:** Other options we evaluated
**Community Feedback:** What contributors said
**Reversible:** Yes/No (and difficulty if yes)
**Impact:** What changed as a result

## Follow-up

[If decision needs revision, link to new decision]
```

## When to Document a Decision

Document decisions that:
- Change APIs or user-facing behavior
- Add/remove major dependencies
- Affect architecture or design patterns
- Set policy or process (testing, CI/CD, contribution)
- Generate community discussion

**Don't document:**
- Bug fixes (unless the fix reveals a design issue)
- Typo corrections
- Minor refactoring within a module

## Decisions by Status

### Adopted

- [2026-01-04: Simplify Templates for Alpha](#2026-01-04-simplify-templates-for-alpha)
- [2026-01-04: Adopt Open Startup Philosophy](#2026-01-04-adopt-open-startup-philosophy)
- [2026-01-01: Python 3.14+ Requirement](#2026-01-01-python-314-requirement)
- [2025-12-15: Pydantic v2 for Models](#2025-12-15-pydantic-v2-for-models)

### Proposed

- None currently

### Deprecated

- None yet

---

## Full Decision History

### 2026-01-04: Simplify Templates for Alpha

**Date:** 2026-01-04
**DRI:** @drchinca
**Status:** Adopted

**Context:**
PR #5 introduced comprehensive GitHub templates (bug report, feature request, PR template) modeled after enterprise open source projects. After expert evaluation, we realized these were overwhelming for an Alpha release.

**Decision:**
Drastically simplify all templates:
- Bug report: 139 → 46 lines
- PR template: 103 → 26 lines
- Remove feature request template (use Discussions instead)
- Remove config.yml (don't disable blank issues)

**Why:**
- Alpha needs low barrier to contribution, not bureaucracy
- Complex templates intimidate first-time contributors
- Feedback quality > structured data at this stage
- Can add structure later as community matures

**Alternatives Considered:**
1. Keep detailed templates, mark fields optional → Still intimidating
2. Two-tier templates (simple + detailed) → Confusing for users
3. Current approach: Start simple, add complexity if needed → **CHOSEN**

**Community Feedback:**
Expert review (sales strategist, solutions architect, CTO perspectives) all agreed templates were too heavy for Alpha soft launch.

**Reversible:** Yes (easy to add back complexity)

**Impact:**
- More approachable for new contributors
- Faster issue/PR creation
- Potential trade-off: Less structured feedback (acceptable for Alpha)

---

### 2026-01-04: Adopt Open Startup Philosophy

**Date:** 2026-01-04
**DRI:** @drchinca
**Status:** Adopted

**Context:**
Preparing for soft launch, we explored "open startup" movement (Buffer, Baremetrics, Meetball) as alternative to traditional open source positioning.

**Decision:**
Adopt open startup principles:
- Radical transparency (metrics, financials, roadmap)
- Community-driven development
- Public decision-making
- Learn in public (share mistakes, not just wins)

**Why:**
- Builds trust with early adopters
- Differentiates from corporate-backed frameworks (LangChain, etc.)
- Attracts contributors who want to be part of something real
- Accountability through public commitments
- Aligns with personal values of founder

**Alternatives Considered:**
1. Traditional open source (just code + docs) → Less differentiated
2. Stealth mode until "ready" → Misses early feedback
3. Corporate-style positioning → Inauthentic for indie project
4. Open startup → **CHOSEN**

**Community Feedback:**
Not yet solicited (pre-launch). Will gather feedback after soft launch.

**Reversible:** Somewhat (can reduce transparency, but breaks trust)

**Impact:**
- Created docs/philosophy.md (10 principles)
- Created OPEN.md (transparent metrics)
- Updated README with "Open Startup" badge
- Commitment to weekly public updates
- Decision log process (this document!)

---

### 2026-01-01: Python 3.14+ Requirement

**Date:** 2026-01-01
**DRI:** @drchinca
**Status:** Adopted

**Context:**
Need to choose minimum Python version. Options: 3.10 (widest compatibility), 3.11 (stable + new), 3.12 (performance), 3.14 (cutting edge).

**Decision:**
Require Python 3.14+ with no backport to older versions.

**Why:**
- **PEP 563:** Postponed evaluation of annotations (cleaner type hints)
- **Better generics:** Improved typing for protocol-based design
- **Performance:** 10-15% faster than 3.10
- **Modern patterns:** Can use latest async/await features
- **Cleaner codebase:** No compatibility shims or workarounds

**Alternatives Considered:**
1. Python 3.10+ (widest compatibility) → Many typing compromises
2. Python 3.11+ (good balance) → Some features still unavailable
3. Python 3.12+ (performance + features) → Missing PEP 563 benefits
4. Python 3.14+ → **CHOSEN**

**Community Feedback:**
- 2 users requested 3.11 support in first week
- Response: Explained rationale, offered to reconsider if demand grows
- Decision: Stick with 3.14+ for now

**Reversible:** Possible but difficult (would require:)
- Removing PEP 563 usage
- Downgrading type hints
- Adding compatibility shims
- Testing across multiple Python versions

**Impact:**
- Smaller initial user base (3.14 adoption still growing)
- Cleaner, more maintainable codebase
- Better developer experience for contributors
- Clear technical positioning (modern Python stack)

---

### 2025-12-15: Pydantic v2 for Models

**Date:** 2025-12-15
**DRI:** @drchinca
**Status:** Adopted

**Context:**
Need runtime validation, serialization, and JSON schema generation for context models, memory scopes, and configuration.

**Decision:**
Use Pydantic v2 for all data models throughout CEMAF.

**Why:**
- **Type safety:** Runtime validation of types
- **Serialization:** Built-in JSON/dict conversion
- **Schema generation:** Automatic JSON schema for docs
- **Developer experience:** Clear error messages
- **Performance:** v2 is built on Rust core (fast)
- **Ecosystem:** Widely adopted in Python data/ML space

**Alternatives Considered:**
1. Python dataclasses → No validation, manual serialization
2. attrs → Less ecosystem support, no schema generation
3. msgspec → Faster but smaller community
4. Pydantic v2 → **CHOSEN**

**Community Feedback:**
None yet (pre-launch decision).

**Reversible:** Very difficult (deeply integrated:)
- All context models inherit BaseModel
- Configuration system uses Pydantic
- Serialization/deserialization throughout
- Would require complete rewrite

**Impact:**
- Contributor learning curve (need Pydantic knowledge)
- Excellent validation error messages for users
- Type-safe APIs throughout
- Dependency on Pydantic (acceptable - stable, maintained)
- Clean integration with FastAPI if users build APIs

---

## Contributing to This Log

When making a major decision:

1. **Create a new file:** `docs/decisions/YYYY-MM-DD-decision-title.md`
2. **Use the template** above
3. **Link from this README** in appropriate status section
4. **Announce in Discord** #announcements
5. **Reference in PR/issue** that implements the decision

Questions about decision log process? [Start a Discussion](https://github.com/drchinca/cemaf/discussions).
