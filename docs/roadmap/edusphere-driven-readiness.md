# CEMAF readiness roadmap — driven by EdusphereMVP milestones

**Purpose.** Keep CEMAF one gate *ahead* of its first substantial consumer.
EdusphereMVP (`drchinca/EdusphereMVP`) adopts CEMAF as the execution substrate
for its Maker/Guardrail/Checker pipeline (see that repo's ADR 0009 and
`project_specs/DELIVERY.md`). Each Edusphere milestone demands specific CEMAF
capabilities; this doc maps those demands onto what CEMAF ships **today**, and
schedules the gap-fills so a capability lands **before** the milestone that
needs it — never after.

**The pattern is proven.** During Edusphere's PoC 000 we found the FSM had no
durable backend and no way to import `cemaf.state` without dragging in every
LLM adapter; both were fixed upstream (below) before M2 framing began. This
roadmap does that systematically for M2→M4.

**Legend** (same grades as Edusphere's ADR 0009):
`✅ Ready` reuse as-is · `🔧 Extend` plumbing exists, needs a gap-fill ·
`🆕 Build` nothing exists · `⚪ Out of scope` Edusphere-owned, not CEMAF's job.

---

## Readiness matrix

| Edusphere need | Milestone | CEMAF today | Grade | CEMAF action |
|---|---|---|---|---|
| Deterministic typed FSM for the Guardrail | M2 | `state.StateMachine` + `Transition` + guards + HITL + append-only history | ✅ | none (reused) |
| Durable FSM across restarts | M2 | `SqliteFsmStore` | ✅ | **DONE** (R1) |
| `import cemaf.state` without loading AI clients | M2 | lazy `cemaf.llm` (PEP 562) | ✅ | **DONE** (R2) |
| Ontology top-K within a candidate slice | M1/M2 | `retrieval.InMemoryVectorStore` cosine + `$in/$nin/$eq/$ne` filter DSL; `HybridRetriever` (RRF) | ✅ | none (reused) |
| `mapped_construct ∈ candidate set` gate | M2 | `citation.StaticSourceRegistry` + `CitationMembershipRule` | ✅ | none (reused) |
| Maker/Checker disagreement → human | M3 | `council` + `DefaultVoteAggregator(UNANIMOUS)` + ballots | ✅ | none (reused; UNANIMOUS caveat documented) |
| Vertex Gemini Flash/Pro adapter | M2/M3 | `llm.GeminiClient(use_vertex=True)` → aiplatform endpoint | ✅ | none (reused) |
| Retry / circuit-breaker on every cloud call | M1+ | `resilience` (retry, breaker, rate limiter) | ✅ | none (reused) |
| Cost/latency/prompt tracing | M1+ | `observability` structured logger + token telemetry | ✅ | none (reused) |
| Local model for ADR 0011 v0.5 rung (Ollama local/tiered/cloud) + deterministic mock Maker backing | E8 | `llm.ollama` (local + tiered router) · `ollama-cloud` backend (ollama.com/v1, bearer auth) · `MockLLMClient` — **all 100% line+branch covered** incl. the resilient-factory wiring | ✅ | **DONE** (R8) |
| **Constrained decoding — force Maker output to a schema** | **M2** | `LLMConfig`/Gemini `_generation_config` have **no `response_schema`/`responseMimeType`**; only post-hoc `ResponseParser` | **🔧** | **R3 — planned, M2 blocker candidate** |
| Nightly batch scheduling for the Checker | M3 | `scheduler`: `CronTrigger`/`IntervalTrigger`/`NightShiftTrigger` + `JobStore` + `LockGate` (idempotent single-run) | ✅ | none (reused) |
| Cloud Tasks as the trigger source | M3 | trigger protocol + in-memory/nightshift triggers only | 🔧 | R4 — thin `Trigger` adapter (or keep in Edusphere `integrations/`) |
| LLM-judge re-audit (PoC 004) | M3 | `evals.LLMJudgeEvaluator`, `HierarchicalJudge`, `GroundednessEvaluator` | ✅ | none (reused) |
| Firestore-backed FSM store for prod | M2/M4 | `FsmStore` protocol + `SqliteFsmStore` as the contract-test template | 🔧 | R5 — decide upstream vs Edusphere `integrations/` |
| **Human pause/resume of a review case** | **M4** | **nothing** — `requires_hitl` gates *who* fires a transition, not durable *suspension*/parking of a task | **🆕** | **R6 — the one true net-new build; prototype during M3** |
| `/evaluaciones` ipsative growth delta, BigQuery | M3 | — | ⚪ | Edusphere analytics; not CEMAF |
| Golden Dataset schema | M4 | — | ⚪ | Edusphere domain; not CEMAF |

---

## CEMAF backlog (sequenced to land ahead of the gate)

Ticket IDs are CEMAF-side; the "unblocks" column points at Edusphere
`DELIVERY.md` tickets so the two backlogs stay joined.

### Shipped (ahead of PoC 000 / M2)

| ID | Title | Status | Unblocks |
|---|---|---|---|
| **R1** | `SqliteFsmStore` — durable FsmStore backend (`backend="sqlite"`), optimistic-lock parity with InMemory | **Done** (this branch) | Guardrail durability; E4-T03 template |
| **R2** | Lazy `cemaf.llm` exports (PEP 562) — protocol imports no longer load provider adapters + httpx | **Done** (this branch) | E4-T01 Guardrail purity gate |
| **R8** | Ollama local/tiered/cloud + MockLLMClient hardened to 100% line+branch coverage (module + factory wiring: env auto-resolution, cloud bearer auth, missing-key error, tiered routing) | **Done** (this branch) | Edusphere **E8-T04/T07** (mock Maker + `run-emulated` Ollama rung) |

### Before the M2 freeze

| ID | Title | Grade | Est. | Detail | Unblocks |
|---|---|---|---|---|---|
| **R3** | **Structured/constrained decoding** in `LLMConfig` + Gemini/Vertex adapter | 🔧 | 2–3 d | Add an optional `response_schema` (+`response_mime_type`) to `LLMConfig`; emit Vertex `responseSchema`/`responseMimeType` in `_generation_config`; surface parse failures as a closed `FinishReason`. Keep `ResponseParser` as the non-supporting-provider fallback. Contract + unit + integration (recorded Vertex response) tests. | Edusphere **E3-T02** (Maker constrained decoding, PoC 003) |

**Why R3 is the priority:** it's the only ✅-adjacent capability M2 needs that
CEMAF can't do today. Edusphere's citation gate is a backstop, but forcing the
schema at decode time is what PoC 003 actually specifies. Land R3 before E3-T02
starts, or E3 carries a provider-parsing workaround that R3 later rips out.

### Before M3

| ID | Title | Grade | Est. | Detail | Unblocks |
|---|---|---|---|---|---|
| **R4** | Cloud Tasks `Trigger` adapter (optional upstream) | 🔧 | 1 d | Implement the `scheduler.Trigger` protocol against Cloud Tasks so the nightly Checker uses CEMAF's scheduler end-to-end. If it stays Edusphere-specific, keep it in `integrations/` and close this as won't-upstream. | Edusphere **E5-T01** |
| **R5** | `FirestoreFsmStore` decision | 🔧 | 1½ d | Either upstream a Firestore `FsmStore` (reusing `SqliteFsmStore`'s test suite as the contract) or ratify keeping it in Edusphere `integrations/`. Protocol + optimistic-lock semantics are CEMAF's; the driver may not need to be. | Edusphere **E4-T03** |
| **R7** | (verify, not build) Confirm `scheduler` + `evals` cover the Checker with no gap | ✅ | ½ d | Spike: `NightShiftTrigger` + `LockGate` + `LLMJudgeEvaluator` wired in a throwaway harness against Edusphere's batch shape. Downgrade to a real ticket only if the spike surfaces a gap. | Edusphere **E5-T02/T06** |

### Before M4 (prototype during M3)

| ID | Title | Grade | Est. | Detail | Unblocks |
|---|---|---|---|---|---|
| **R6** | **Durable pause/resume primitive** (ADR 0009 row 9 — the 🔴) | 🆕 | 3–5 d | The only capability nothing in CEMAF covers. Design first: is it a `state` extension (a suspended super-state with a durable resume token + reason) or a `scheduler` durable-park (`JobStore` entry parked pending a human signal)? Prototype behind a spike during M3 so M4 doesn't start on a blank page. Contract + unit + integration (suspend → restart process → resume with state intact). Candidate flagship CEMAF feature, not an Edusphere one-off. | Edusphere **E6-T04** |

---

## Sequencing rule

```
 CEMAF:   R1,R2 ──▶ R3 ─────────▶ R4,R5,R7 ─────▶ R6 (build)
 done ✅          before M2 freeze   before M3        before M4
 Edu:     PoC000 ─▶ M2 (E3/E4) ────▶ M3 (E5) ──────▶ M4 (E6)
```

Each CEMAF ticket must be `Done` (merged, tested on Python 3.14 CI) **before**
the Edusphere ticket in its "unblocks" column reaches `In progress`. A CEMAF
gap discovered mid-Edusphere-ticket (like R1 was) is logged here, fixed
upstream, and the Edusphere ticket pinned to the new rev — never worked around
silently.

## What this roadmap deliberately does NOT put in CEMAF

CEMAF stays domain- and task-agnostic (its CLAUDE.md prime directive). The
ipsative growth delta, the ontology *content*, the Golden Dataset schema, the
Firestore *data model*, and the Calibration Tray UI are all Edusphere's — CEMAF
provides the FSM, retrieval, citation, council, scheduling, eval, and (R6) the
pause/resume substrate they run on, nothing above that line.
