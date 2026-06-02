"""POC: Tool-output bucket pruning (M1 vs M2 vs M3).

Scenario: 50 tool outputs at 2KB each = ~100KB total. Budget = 40KB.
Plus 5 long-lived memories (8KB total, priority=7).
Plus 1 system prompt (1KB, priority=100).

Measures:
- Total tokens used
- Recent-N preservation (% of last 20 tool outputs surviving)
- Stale-N eviction (% of first 20 tool outputs evicted)
- Memory/system-prompt preservation (must survive)
- Pruning latency

Run: uv run python docs/pocs/_experiments/tool_output_bucket_bench.py
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cemaf.context.source import ContextSource, ContextType
from cemaf.core.types import TokenCount
from cemaf.core.utils import utc_now

CHARS_PER_TOKEN = 4  # rough heuristic for the bench

TOOL_OUTPUT_BYTES = 2_000  # POC #1 wrapper cap
NUM_TOOL_OUTPUTS = 50
NUM_MEMORIES = 5
MEM_BYTES = 1_600
SYSTEM_BYTES = 1_000
BUDGET_TOKENS = 10_000  # 40k chars
PROTECT_LAST_TOKENS = 4_000  # opencode-style PRUNE_PROTECT — reserve 40% of 10k budget for recent tool outputs


def chars_to_tokens(n: int) -> TokenCount:
    return TokenCount(n // CHARS_PER_TOKEN)


def make_sources() -> list[ContextSource]:
    base_time = utc_now() - timedelta(hours=2)
    sources: list[ContextSource] = []
    sources.append(
        ContextSource(
            content="x" * SYSTEM_BYTES,
            token_count=chars_to_tokens(SYSTEM_BYTES),
            priority=100,
            timestamp=base_time,
            source_type="system_prompt",
            source_id="sys",
        )
    )
    for i in range(NUM_MEMORIES):
        sources.append(
            ContextSource(
                content="m" * MEM_BYTES,
                token_count=chars_to_tokens(MEM_BYTES),
                priority=7,
                timestamp=base_time + timedelta(minutes=i),
                source_type="memory",
                source_id=f"mem_{i}",
                context_type=ContextType.MEMORY,
            )
        )
    for i in range(NUM_TOOL_OUTPUTS):
        sources.append(
            ContextSource(
                content="t" * TOOL_OUTPUT_BYTES,
                token_count=chars_to_tokens(TOOL_OUTPUT_BYTES),
                priority=5,
                timestamp=base_time + timedelta(minutes=10 + i),
                source_type="tool_output",
                source_id=f"tool_{i:02d}",
                context_type=ContextType.RESOURCE,
                metadata={"turn": i},
            )
        )
    return sources


# --- M1: greedy priority + recency, no bucket logic ---


def m1_select(sources: list[ContextSource], budget_tokens: int) -> tuple[list[ContextSource], float]:
    t0 = time.perf_counter()
    ranked = sorted(sources)  # ContextSource.__lt__ already orders higher-priority first
    selected: list[ContextSource] = []
    used = 0
    for s in ranked:
        cost = int(s.token_count or 0)
        if used + cost <= budget_tokens:
            selected.append(s)
            used += cost
    dur_ms = (time.perf_counter() - t0) * 1000
    return selected, dur_ms


# --- M2: TOOL_OUTPUT bucket pre-pruner + greedy on rest ---


@dataclass(frozen=True)
class ToolOutputBucket:
    protect_last_tokens: int

    def prune(self, sources: list[ContextSource]) -> tuple[list[ContextSource], list[ContextSource]]:
        """Return (kept_tool_outputs, evicted_tool_outputs). Non-tool sources untouched."""
        tool_sources = [s for s in sources if s.source_type == "tool_output"]
        tool_sources.sort(key=lambda s: s.timestamp, reverse=True)
        kept: list[ContextSource] = []
        evicted: list[ContextSource] = []
        used = 0
        for s in tool_sources:
            cost = int(s.token_count or 0)
            if used + cost <= self.protect_last_tokens:
                kept.append(s)
                used += cost
            else:
                evicted.append(s)
        return kept, evicted


def m2_select(sources: list[ContextSource], budget_tokens: int, reserve_for_tools: int) -> tuple[list[ContextSource], float, int]:
    """M2: reserve a sub-budget for tool outputs (LRU within reservation), priority-select rest."""
    t0 = time.perf_counter()
    bucket = ToolOutputBucket(protect_last_tokens=reserve_for_tools)
    kept_tools, evicted_tools = bucket.prune(sources)
    tool_tokens_used = sum(int(s.token_count or 0) for s in kept_tools)

    non_tools = [s for s in sources if s.source_type != "tool_output"]
    remaining_budget = budget_tokens - tool_tokens_used
    ranked = sorted(non_tools)
    selected_nt: list[ContextSource] = []
    used = 0
    for s in ranked:
        cost = int(s.token_count or 0)
        if used + cost <= remaining_budget:
            selected_nt.append(s)
            used += cost
    selected = selected_nt + kept_tools
    dur_ms = (time.perf_counter() - t0) * 1000
    return selected, dur_ms, len(evicted_tools)


# --- M3: priority decay per turn for tool_output ---


def m3_select(sources: list[ContextSource], budget_tokens: int, decay_per_turn: float = 0.5) -> tuple[list[ContextSource], float]:
    t0 = time.perf_counter()
    max_turn = max((int(s.metadata.get("turn", 0)) for s in sources if s.source_type == "tool_output"), default=0)

    def decayed_priority(s: ContextSource) -> float:
        if s.source_type != "tool_output":
            return float(s.priority)
        age = max_turn - int(s.metadata.get("turn", 0))
        return float(s.priority) - decay_per_turn * age

    ranked = sorted(sources, key=lambda s: (-decayed_priority(s), -s.timestamp.timestamp()))
    selected: list[ContextSource] = []
    used = 0
    for s in ranked:
        cost = int(s.token_count or 0)
        if used + cost <= budget_tokens:
            selected.append(s)
            used += cost
    dur_ms = (time.perf_counter() - t0) * 1000
    return selected, dur_ms


def stats(label: str, selected: list[ContextSource], dur_ms: float, *, evicted_count: int | None = None) -> dict[str, Any]:
    tool_ids = sorted(int(s.source_id.split("_")[1]) for s in selected if s.source_type == "tool_output")
    last_20 = set(range(NUM_TOOL_OUTPUTS - 20, NUM_TOOL_OUTPUTS))
    first_20 = set(range(20))
    recent_kept = len([t for t in tool_ids if t in last_20])
    stale_kept = len([t for t in tool_ids if t in first_20])
    used_tokens = sum(int(s.token_count or 0) for s in selected)
    has_system = any(s.source_id == "sys" for s in selected)
    mem_kept = sum(1 for s in selected if s.source_type == "memory")
    return {
        "label": label,
        "total_selected": len(selected),
        "tool_outputs_kept": len(tool_ids),
        "recent_20_preserved_pct": (recent_kept / 20) * 100,
        "stale_20_evicted_pct": ((20 - stale_kept) / 20) * 100,
        "memory_kept": f"{mem_kept}/{NUM_MEMORIES}",
        "system_prompt_kept": has_system,
        "used_tokens": used_tokens,
        "budget_tokens": BUDGET_TOKENS,
        "evictions_logged": evicted_count if evicted_count is not None else "n/a",
        "duration_ms": round(dur_ms, 4),
    }


def make_sources_high_priority_competition() -> list[ContextSource]:
    """Variant: many high-priority docs (priority=20) that crowd out tool outputs under M1."""
    base_time = utc_now() - timedelta(hours=2)
    sources: list[ContextSource] = []
    sources.append(
        ContextSource(
            content="x" * SYSTEM_BYTES,
            token_count=chars_to_tokens(SYSTEM_BYTES),
            priority=100,
            timestamp=base_time,
            source_type="system_prompt",
            source_id="sys",
        )
    )
    # 20 "important docs" each 1KB at priority 20 — crowds out tool outputs in M1
    for i in range(20):
        sources.append(
            ContextSource(
                content="d" * 1000,
                token_count=chars_to_tokens(1000),
                priority=20,
                timestamp=base_time + timedelta(minutes=i),
                source_type="document",
                source_id=f"doc_{i:02d}",
            )
        )
    for i in range(NUM_MEMORIES):
        sources.append(
            ContextSource(
                content="m" * MEM_BYTES,
                token_count=chars_to_tokens(MEM_BYTES),
                priority=7,
                timestamp=base_time + timedelta(minutes=100 + i),
                source_type="memory",
                source_id=f"mem_{i}",
                context_type=ContextType.MEMORY,
            )
        )
    for i in range(NUM_TOOL_OUTPUTS):
        sources.append(
            ContextSource(
                content="t" * TOOL_OUTPUT_BYTES,
                token_count=chars_to_tokens(TOOL_OUTPUT_BYTES),
                priority=5,
                timestamp=base_time + timedelta(minutes=200 + i),
                source_type="tool_output",
                source_id=f"tool_{i:02d}",
                context_type=ContextType.RESOURCE,
                metadata={"turn": i},
            )
        )
    return sources


def run_scenario(label: str, sources: list[ContextSource]) -> None:
    print(f"\n=== Scenario: {label} ===")
    total_input_tokens = sum(int(s.token_count or 0) for s in sources)
    print(f"Input: {len(sources)} sources, {total_input_tokens} tokens")
    print(f"Budget: {BUDGET_TOKENS} tokens, PROTECT_LAST_TOKENS: {PROTECT_LAST_TOKENS}\n")

    def repeat(fn, n=50):
        durs = []
        last = None
        for _ in range(n):
            res = fn()
            durs.append(res[1])
            last = res
        return last, statistics.median(sorted(durs))

    m1_last, m1_p50 = repeat(lambda: m1_select(sources, BUDGET_TOKENS))
    m2_last, m2_p50 = repeat(lambda: m2_select(sources, BUDGET_TOKENS, PROTECT_LAST_TOKENS))
    m2a_last, m2a_p50 = repeat(lambda: m2_adaptive_select(sources, BUDGET_TOKENS, PROTECT_LAST_TOKENS))
    m3_last, m3_p50 = repeat(lambda: m3_select(sources, BUDGET_TOKENS))

    rows = [
        stats("M1 (status quo)", m1_last[0], m1_p50),
        stats("M2 (reserve-only)", m2_last[0], m2_p50, evicted_count=m2_last[2]),
        stats("M2a (adaptive)", m2a_last[0], m2a_p50, evicted_count=m2a_last[2]),
        stats("M3 (decay)", m3_last[0], m3_p50),
    ]
    headers = list(rows[0].keys())
    print(" | ".join(headers))
    print("-" * 140)
    for r in rows:
        print(" | ".join(str(r[h]) for h in headers))


def m2_adaptive_select(sources: list[ContextSource], budget_tokens: int, reserve: int) -> tuple[list[ContextSource], float, int]:
    """M2-adaptive: reserve floor for tool outputs, but bucket may grow up to budget if non-tool sources fit first.

    Algorithm:
    1. Reserve `reserve` tokens for recent tool outputs (LRU bucket).
    2. Run priority selection on non-tool sources up to (budget - reserve).
    3. If non-tool selection used less than (budget - reserve), give the slack back to the bucket.
    """
    t0 = time.perf_counter()
    non_tools = [s for s in sources if s.source_type != "tool_output"]
    ranked_nt = sorted(non_tools)
    selected_nt: list[ContextSource] = []
    used_nt = 0
    nt_cap = budget_tokens - reserve
    for s in ranked_nt:
        cost = int(s.token_count or 0)
        if used_nt + cost <= nt_cap:
            selected_nt.append(s)
            used_nt += cost

    tool_budget = budget_tokens - used_nt
    bucket = ToolOutputBucket(protect_last_tokens=tool_budget)
    kept_tools, evicted_tools = bucket.prune(sources)

    selected = selected_nt + kept_tools
    dur_ms = (time.perf_counter() - t0) * 1000
    return selected, dur_ms, len(evicted_tools)


def main() -> None:
    run_scenario("baseline (no priority competition)", make_sources())
    run_scenario("high-priority docs crowd tool outputs", make_sources_high_priority_competition())


if __name__ == "__main__":
    main()
