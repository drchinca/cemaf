"""POC: Model catalog driven selection (M1 vs M2 vs M3).

Scenarios — each is a (request_profile, hand_picked_optimal_model) pair:
1. tiny request, no tools                  → cheapest small model
2. medium tool-using request               → cheap model that supports tools
3. 200k-token request                      → only models with ≥200k window
4. vision-required request                 → only vision-capable models
5. high-complexity coding request          → biggest reasoning model
6. cheap-bias mode                         → cheaper of two equally-capable

Methods scored by % of scenarios where they pick the hand-picked optimal.

Run: uv run python docs/pocs/_experiments/model_catalog_bench.py
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ModelSpec(BaseModel):
    provider: str
    model_id: str
    context_window: int
    max_output_tokens: int
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    supports_tools: bool = True
    supports_vision: bool = False
    supports_caching: bool = False
    deprecated: bool = False
    aliases: tuple[str, ...] = Field(default=())

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model_id}"


CATALOG: list[ModelSpec] = [
    ModelSpec(
        provider="anthropic",
        model_id="claude-haiku-4-5",
        context_window=200_000,
        max_output_tokens=8192,
        input_cost_per_mtok=0.80,
        output_cost_per_mtok=4.00,
        supports_tools=True,
        supports_caching=True,
    ),
    ModelSpec(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        context_window=200_000,
        max_output_tokens=8192,
        input_cost_per_mtok=3.00,
        output_cost_per_mtok=15.00,
        supports_tools=True,
        supports_vision=True,
        supports_caching=True,
    ),
    ModelSpec(
        provider="anthropic",
        model_id="claude-opus-4-7",
        context_window=200_000,
        max_output_tokens=8192,
        input_cost_per_mtok=15.00,
        output_cost_per_mtok=75.00,
        supports_tools=True,
        supports_vision=True,
        supports_caching=True,
    ),
    ModelSpec(
        provider="openai",
        model_id="gpt-4o-mini",
        context_window=128_000,
        max_output_tokens=16384,
        input_cost_per_mtok=0.15,
        output_cost_per_mtok=0.60,
        supports_tools=True,
        supports_vision=True,
    ),
    ModelSpec(
        provider="openai",
        model_id="gpt-4o",
        context_window=128_000,
        max_output_tokens=16384,
        input_cost_per_mtok=2.50,
        output_cost_per_mtok=10.00,
        supports_tools=True,
        supports_vision=True,
    ),
    ModelSpec(
        provider="ollama",
        model_id="gemma3:4b",
        context_window=8_192,
        max_output_tokens=2048,
        input_cost_per_mtok=0.0,
        output_cost_per_mtok=0.0,
        supports_tools=False,
    ),
    ModelSpec(
        provider="ollama",
        model_id="gemma3:12b",
        context_window=32_768,
        max_output_tokens=4096,
        input_cost_per_mtok=0.0,
        output_cost_per_mtok=0.0,
        supports_tools=False,
    ),
]


@dataclass(frozen=True)
class Request:
    estimated_input_tokens: int
    estimated_output_tokens: int
    needs_tools: bool
    needs_vision: bool
    complexity: float  # 0..1
    name: str


SCENARIOS: list[tuple[Request, str]] = [
    (Request(500, 200, False, False, 0.05, "tiny no-tools"), "ollama:gemma3:4b"),
    (Request(8_000, 2_000, True, False, 0.3, "medium tool use"), "openai:gpt-4o-mini"),
    (Request(180_000, 4_000, True, False, 0.7, "200k window"), "anthropic:claude-haiku-4-5"),
    (Request(4_000, 1_000, True, True, 0.4, "vision required"), "openai:gpt-4o-mini"),
    (Request(40_000, 6_000, True, False, 0.95, "complex coding"), "anthropic:claude-opus-4-7"),
    (Request(2_000, 800, True, False, 0.2, "cheap bias"), "openai:gpt-4o-mini"),
]


# --- M1: status quo — complexity threshold router with fixed routes ---


@dataclass(frozen=True)
class ThresholdRoute:
    threshold: float
    model_key: str


M1_ROUTES = [
    ThresholdRoute(0.2, "ollama:gemma3:4b"),
    ThresholdRoute(0.5, "openai:gpt-4o-mini"),
    ThresholdRoute(0.8, "anthropic:claude-sonnet-4-6"),
    ThresholdRoute(1.01, "anthropic:claude-opus-4-7"),
]


def m1_select(req: Request) -> str:
    for route in M1_ROUTES:
        if req.complexity < route.threshold:
            return route.model_key
    return M1_ROUTES[-1].model_key


# --- M2: pure catalog-driven cost minimization with capability + window gates ---


def m2_select(req: Request, catalog: list[ModelSpec]) -> str:
    candidates: list[ModelSpec] = []
    for spec in catalog:
        if spec.deprecated:
            continue
        if req.needs_tools and not spec.supports_tools:
            continue
        if req.needs_vision and not spec.supports_vision:
            continue
        if spec.context_window < req.estimated_input_tokens + req.estimated_output_tokens:
            continue
        candidates.append(spec)

    if not candidates:
        raise RuntimeError(f"No model fits request {req.name}")

    def cost(spec: ModelSpec) -> float:
        ic = (spec.input_cost_per_mtok or 0.0) * req.estimated_input_tokens / 1e6
        oc = (spec.output_cost_per_mtok or 0.0) * req.estimated_output_tokens / 1e6
        return ic + oc

    candidates.sort(key=cost)
    return candidates[0].key


# --- M3: hybrid — capability + window gate, then complexity-aware cost selection ---


def m3_select(req: Request, catalog: list[ModelSpec], *, quality_floor_curve: tuple[tuple[float, float], ...] = ((0.5, 0.0), (0.85, 0.5), (1.01, 12.0))) -> str:
    """Hybrid: hard filter by capability + window, then cheapest model whose input price ≥ a complexity-driven quality floor.

    quality_floor_curve maps complexity threshold → minimum input_cost_per_mtok (a proxy for model quality tier).
    Default: complexity<0.3 → 0 (allow free local models); <0.6 → ≥$1/Mtok; <0.85 → ≥$5/Mtok; else ≥$12/Mtok.
    Within the qualified set, pick cheapest.
    """
    candidates: list[ModelSpec] = []
    for spec in catalog:
        if spec.deprecated:
            continue
        if req.needs_tools and not spec.supports_tools:
            continue
        if req.needs_vision and not spec.supports_vision:
            continue
        if spec.context_window < req.estimated_input_tokens + req.estimated_output_tokens:
            continue
        candidates.append(spec)

    if not candidates:
        raise RuntimeError(f"No model fits request {req.name}")

    quality_floor = 0.0
    for threshold, floor in quality_floor_curve:
        if req.complexity < threshold:
            quality_floor = floor
            break

    qualified = [s for s in candidates if (s.input_cost_per_mtok or 0.0) >= quality_floor]
    if not qualified:
        qualified = candidates  # nobody meets floor — fall back to all candidates

    def cost(spec: ModelSpec) -> float:
        ic = (spec.input_cost_per_mtok or 0.0) * req.estimated_input_tokens / 1e6
        oc = (spec.output_cost_per_mtok or 0.0) * req.estimated_output_tokens / 1e6
        return ic + oc

    qualified.sort(key=cost)
    return qualified[0].key


def main() -> None:
    print(f"Catalog: {len(CATALOG)} models, {len(SCENARIOS)} scenarios\n")

    # Latency: 500-iter selections
    def time_select(fn, req):
        durs = []
        for _ in range(500):
            t0 = time.perf_counter()
            fn(req)
            durs.append((time.perf_counter() - t0) * 1000)
        return statistics.median(sorted(durs))

    sample_req = SCENARIOS[0][0]
    m1_p50 = time_select(lambda r: m1_select(r), sample_req)
    m2_p50 = time_select(lambda r: m2_select(r, CATALOG), sample_req)
    m3_p50 = time_select(lambda r: m3_select(r, CATALOG), sample_req)

    # Catalog load latency
    t0 = time.perf_counter()
    for spec in CATALOG:
        ModelSpec.model_validate(spec.model_dump())
    catalog_load_ms = (time.perf_counter() - t0) * 1000

    results: dict[str, list[dict[str, Any]]] = {"M1": [], "M2": [], "M3": []}
    correctness: dict[str, int] = {"M1": 0, "M2": 0, "M3": 0}
    capability_violations: dict[str, int] = {"M1": 0, "M2": 0, "M3": 0}
    window_violations: dict[str, int] = {"M1": 0, "M2": 0, "M3": 0}

    catalog_by_key = {s.key: s for s in CATALOG}

    for req, optimal in SCENARIOS:
        for label, fn in [("M1", lambda r: m1_select(r)), ("M2", lambda r: m2_select(r, CATALOG)), ("M3", lambda r: m3_select(r, CATALOG))]:
            try:
                pick = fn(req)
            except Exception as e:
                pick = f"ERROR: {e}"
            spec = catalog_by_key.get(pick)
            cap_violation = bool(spec and ((req.needs_tools and not spec.supports_tools) or (req.needs_vision and not spec.supports_vision)))
            win_violation = bool(spec and spec.context_window < req.estimated_input_tokens + req.estimated_output_tokens)
            if cap_violation:
                capability_violations[label] += 1
            if win_violation:
                window_violations[label] += 1
            if pick == optimal:
                correctness[label] += 1
            results[label].append({"scenario": req.name, "pick": pick, "optimal": optimal, "match": pick == optimal, "cap_ok": not cap_violation, "win_ok": not win_violation})

    print(f"Catalog load (validate {len(CATALOG)} specs): {catalog_load_ms:.3f} ms")
    print(f"Selection p50: M1={m1_p50:.4f}ms  M2={m2_p50:.4f}ms  M3={m3_p50:.4f}ms\n")
    print("Per-method correctness vs hand-picked optimal:")
    n = len(SCENARIOS)
    for label in ["M1", "M2", "M3"]:
        print(f"  {label}: {correctness[label]}/{n} ({100*correctness[label]/n:.0f}%)  capability_violations={capability_violations[label]}  window_violations={window_violations[label]}")

    print("\nDetail:")
    for label in ["M1", "M2", "M3"]:
        print(f"\n  {label}")
        for r in results[label]:
            mark = "✓" if r["match"] else "✗"
            cap = " CAP-VIOLATION" if not r["cap_ok"] else ""
            win = " WINDOW-VIOLATION" if not r["win_ok"] else ""
            print(f"    {mark} {r['scenario']:<22} → {r['pick']:<40}  (optimal: {r['optimal']}){cap}{win}")


if __name__ == "__main__":
    main()
