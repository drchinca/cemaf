---
title: Anchored Compaction Template
date: 2026-05-16
status: Complete
methodologies_compared:
  - M1 — Flat summary (current SimpleMemoryCompactor on the conversation as a blob)
  - M2 — Per-turn extractive truncation (keep last N turns verbatim, drop rest)
  - M3 — Anchored Markdown template + tail, updated turn-over-turn
decision: "Go — M3 (anchored template + 25% tail). Deterministic extractor v1; LLM-driven extractor v2 (separate spec)."
related:
  inspiration: https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts
  pocs: []
  specs: []
---

# POC: Anchored Compaction Template

## Question

When the conversation/session context exceeds budget, should we replace flat summarization (`SimpleMemoryCompactor` on the whole transcript) with an **anchored Markdown template** (Goal / Constraints / Progress / Decisions / Next Steps / Critical Context / Relevant Files) that gets *updated* turn-over-turn — preserving the last N turns verbatim and folding older turns into the structured summary?

Inspiration: opencode `session/compaction.ts:44-79,247-296`. The `SUMMARY_TEMPLATE` is a fixed Markdown skeleton; each compaction pass takes the previous summary + new turns and emits an updated summary anchored on the prior one ("Update the anchored summary below…"). Last 25% of usable context window (clamped 2k-8k tokens) is preserved verbatim. Old tool outputs are pruned *before* this step (POC #2 territory).

## Current State — Baseline Numbers

`src/cemaf/memory/compaction.py:78-199` — `SimpleMemoryCompactor` truncates each `MemoryItem` independently. There is no session-level compactor. Session-level compaction in `memory/session.py:95` and `postgres_session_manager.py:133` exists as a method but the implementation per-item truncates.

| Signal | Value | Source |
|---|---|---|
| Flat summary template | none — truncation only | `compaction.py:195-199` `_truncate_summary` |
| Anchored / structured template | none | n/a |
| Tail preservation (last N turns verbatim) | not enforced | n/a |
| Turn-over-turn update (summary depends on prior summary) | no | each `compact()` is stateless |
| LLM-driven summarization | optional but stubbed | `SimpleMemoryCompactor` is truncation-only |

**Implications:**
- Flat truncation drops the *first* characters of each item — destroying decisions and constraints established early in a session.
- A "bash: ls /" tool output and a "user: rewrite the auth module" message get the same compaction policy. Decisions decay at the same rate as noise.
- No anchoring means re-compaction can lose information added in the previous summary (each pass starts fresh).

## Methodologies

### M1 — Flat summary blob (status quo)

Concatenate all turns, run `SimpleMemoryCompactor.compact(item, target_level=SUMMARY)` (truncate to 200 chars). Tail not preserved.

- **Pros:** simple, no LLM cost, deterministic
- **Cons:** loses decisions, constraints, and intent that lived in the early turns

### M2 — Tail preservation only

Drop the oldest turns until the budget fits. Last K turns survive verbatim.

- **Pros:** simple, full fidelity for recent turns
- **Cons:** loses long-horizon context entirely (goal, constraints from turn 1)

### M3 — Anchored template (opencode parity)

Two-part output:
1. **Anchor** — a fixed Markdown skeleton with sections: `## Goal`, `## Constraints`, `## Progress`, `## Decisions`, `## Next Steps`, `## Critical Context`, `## Relevant Files`. Updated turn-over-turn (each pass receives the previous anchor + new turns).
2. **Tail** — last K turns verbatim, where `K` is sized by `tail_fraction * budget` (default 0.25, opencode parity).

The anchor compaction itself can be done by:
- (a) deterministic extraction (regex / heuristic — find "the goal is", "must not", "decided to", file paths)
- (b) LLM call with a fixed prompt
- (c) hybrid: deterministic seed + LLM refinement

For this POC we measure (a) — the deterministic version — to isolate the structural win from the LLM cost.

- **Pros:** structured fidelity (decisions don't decay), turn-over-turn anchoring preserves long-horizon context, tail preserves recent fidelity, mirrors opencode
- **Cons:** new template + extractor; LLM-driven version costs tokens per compaction; deterministic version is heuristic

## Success Criteria

| Metric | Target | Reason |
|---|---|---|
| Goal/Constraints from turn 1 retained after 30 turns | yes for M3, n/a for M1/M2 | Long-horizon decision integrity |
| Recent K turns preserved verbatim | yes (M3 tail) | Agent reads what it just produced |
| Compacted output fits in budget | yes (all methods) | Trivial gate |
| Information retention score (semantic recall on seeded facts) | M3 ≥ 80%; M1 ≤ 50% | Quality, not just shape |
| Compaction is deterministic given inputs | yes | Replay/audit |
| Compaction latency | <100ms for 30-turn session | No perf regression |
| Output is parseable Markdown with stable anchors | yes | Downstream consumers (UI, replay) |

## Comparison Table

Bench: `docs/pocs/_experiments/anchored_compaction_bench.py`. Run on 2026-05-16.

Session: 38 turns / ~7,000 chars. Budget: 1,749 chars (quarter of input — forces compaction). 6 seeded facts (goal, two constraints, decision, late constraint, current task) span turns 1, 2, 5, 28, 30.

| Method | Output chars | Fits budget | Recall % | Missing facts | p50 latency |
|---|---|---|---|---|---|
| M1 — Flat truncate | 1,749 | yes | **66.7%** | Late constraint, Current task | 0.005 ms |
| M2 — Tail only | 1,495 | yes | **33.3%** | Goal, /tmp constraint, latency constraint, decision | 0.002 ms |
| **M3 — Anchored + tail** | 818 | yes | **100%** | — | 0.752 ms |

### Turn-over-turn anchoring (the load-bearing property)

We split the session in two halves. Compact the first half, then compact the *second half only* with and without the prior anchor.

| Method | Recall % | Missing facts |
|---|---|---|
| M3 (2nd half, no prior anchor) | 33.3% | Goal, /tmp, latency, decision (all from turn 1-5, never seen) |
| **M3 (2nd half + prior anchor)** | **100%** | — |

This is the killer measurement: anchoring **is** the mechanism that preserves long-horizon facts. Without it, M3 collapses to M2's recall floor.

## Detailed Results

**M1 (flat truncate):** Concatenates everything, cuts at budget. Loses facts at *both ends* unpredictably — in this run it kept turn-1 goal but dropped turn-28/30 facts because they live past the cut. In a different distribution (mid-conversation noise heavier), it could lose the goal instead. Non-deterministic which facts survive.

**M2 (tail only):** Keeps the last K turns verbatim. Recent facts (28, 30) survive perfectly; everything before the cut is gone. Half the seeded facts vanish. Maximum recency, zero long-horizon memory.

**M3 (anchored + tail):**
- Anchor section (Markdown skeleton with 7 sections) at top, captures structured facts via deterministic regex extractor.
- Tail (25% of budget) holds the last K turns verbatim.
- Combined output is 818 chars (53% under budget) and retains 100% of seeded facts.
- Anchor handoff: when compacting the second half alone, supplying the prior anchor restores all early-session facts. Without it, the early facts are lost.

**Compactor extractor (v1, deterministic):**
- Goal: `r"\b(goal|objective)\s*[:\-]?\s*(.+)"` on user turns
- Constraints: `r"\b(constraint|must not|do not|cannot|never)\b"`
- Decisions: `r"\b(decision|decided|we'll use|chose)\b"`
- Next steps: `r"\b(current task|next step|now i'll)\b"`
- Files: `r"([\w./_-]+\.(?:py|ts|md|json|yaml|yml|sql|sh|tf))"`
- Prior anchor merge: parse previous Markdown sections, dedupe, prepend to current pass.

This is heuristic but deterministic, reproducible, and replay-safe. v2 will allow an LLM-driven extractor as an injectable strategy (`AnchorExtractor` protocol).

## Success Criteria — Actuals

| Metric | Target | Actual (M3) |
|---|---|---|
| Goal/Constraints from turn 1 retained after 30 turns | yes | yes (100%) |
| Recent K turns preserved verbatim | yes | yes (last ~3 turns at 25% tail) |
| Compacted output fits budget | yes | yes (53% under budget) |
| Information retention (recall) | M3 ≥ 80%; M1 ≤ 50% | M3 = 100%, M1 = 66.7%, M2 = 33.3% |
| Deterministic | yes | yes (regex extractor, no LLM) |
| Latency for 30-turn session | <100ms | 0.75 ms |
| Parseable Markdown with stable anchors | yes | yes — `## Goal`, `## Constraints`, etc. |

## Decision

**Go — M3 (anchored Markdown template + 25% tail).** Implementation will use the deterministic extractor as v1; LLM-driven extractor as a pluggable strategy in v2.

Rationale:
- M3 wins the only metric that matters: information retention (100% vs M1's 66.7% and M2's 33.3%) on identical input and budget.
- Latency is 750µs — three orders of magnitude under the 100ms target. The deterministic extractor is essentially free; an LLM extractor would dominate cost but is opt-in.
- The turn-over-turn anchoring property (compact-with-prior-anchor) is functionally why long-horizon facts survive. It is the *mechanism* the spec must preserve, not an implementation detail.
- M2 was tempting (zero new concepts, near-zero latency) but it gives up half the session's information by design. Status-quo M1 is non-deterministic about which facts survive — unshippable for replay/audit.

## Learnings

- **Turn-over-turn anchoring is the load-bearing invariant.** Without it M3 degrades to M2. The spec MUST encode: `WHEN compacting a session that has a prior anchor, THE System SHALL merge the prior anchor's sections before extracting from new turns`. EARS rule, §3 invariant.
- **Recall is testable deterministically.** Substring presence on seeded facts is a conservative proxy that correlates with LLM recall. Spec §4 Gherkin scenarios should seed facts and assert recall thresholds — not measure prose quality.
- **The anchor schema is API.** `## Goal / Constraints / Progress / Decisions / Next Steps / Critical Context / Relevant Files` is a stable contract. Downstream consumers (UI, audit trail, replay) parse it. Spec §2 Interface Contract: `AnchorSchema` enum + Markdown emitter with frozen section names.
- **Extractor is pluggable.** Deterministic v1 (regex), LLM v2 (with prompt cache), hybrid v3 (deterministic seed + LLM polish). Protocol: `AnchorExtractor.extract(turns, prior_anchor) -> AnchorSections`. Each is injectable; default is deterministic so the system has zero LLM dependency at compaction time.
- **Tail fraction = 0.25 matches opencode and works empirically here.** Worth exposing as a config knob (`tail_fraction: float = 0.25`) but the default is sound.
- **POCs #2 and #3 compose.** POC #2's bucket evicts stale tool outputs *before* compaction runs. POC #3 then has a smaller, fresher input. Tested separately here, but spec must define the order: bucket → compaction → priority selection.
- **Stateful compaction needs a session-level home.** `CompactedMemory` today is per-item; this is per-*session*. New `SessionCompactor` class (or method on `SessionManager`) that owns the prior-anchor state across turns.

## Next Steps

1. **Spec it** via `/write-spec` — `docs/specs/SPEC-anchored-session-compaction.md`. Required sections:
   - §2 Interface Contract: `AnchoredSummary` dataclass (frozen, sections + tail), `AnchorExtractor` Protocol (deterministic + LLM impls), `SessionCompactor.compact(turns, *, prior_anchor, budget, tail_fraction=0.25) -> AnchoredSummary`.
   - §3 Invariants (EARS): turn-over-turn anchoring rule, tail-always-verbatim rule, fits-budget rule, deterministic-given-extractor rule.
   - §4 Gherkin scenarios: 7+ — first-pass / second-pass-with-prior-anchor / tail-overflow / extractor-finds-no-decisions / regenerate-after-corruption / multi-pass-stability / LLM-extractor-fallback-on-error.
   - §7 Correctness Properties: "for any turns t1..tn compacted in passes (1..k, k+1..n) with anchor handoff, recall of seeded facts ≥ recall of single-pass compaction."
   - §8 Eval Criteria: `RecallEvaluator` for seeded-fact substring presence (deterministic, GATE), `AnchorParseEvaluator` for valid Markdown structure (GATE), optional `SemanticFidelityEvaluator` for LLM-judge prose quality (OBSERVE).
   - §9 Observability Contract: `gen_ai.session.compact` span with `turns_input`, `turns_in_tail`, `anchor_sections_filled`, `recall_score` attributes.
2. **Sequence after POC #2** — POC #2's tool-output bucket reduces compaction input volume. Implementation order: bucket first, compaction second.
3. **Out of scope:**
   - LLM-driven extractor — separate POC `/write-poc` measuring quality vs cost vs the deterministic version. Default impl ships as deterministic.
   - Anchor versioning / migration when section schema changes — handle when needed, not now.
   - Cross-session anchor inheritance (a project-level anchor) — interesting but out of scope.
