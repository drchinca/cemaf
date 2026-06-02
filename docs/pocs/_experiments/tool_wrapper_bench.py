"""POC: Tool execution wrapper bench (M1 vs M2 vs M3).

Measures:
- Span coverage (binary per tool)
- Output truncation enforcement
- Per-execute overhead p50/p99
- Validation-error format uniformity
- LOC delta when boilerplate is removed

Run: uv run python docs/pocs/_experiments/tool_wrapper_bench.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.tools.base import Tool, ToolResult, ToolSchema


@dataclass
class SpanRecord:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []

    def span(self, name: str, **attrs: Any) -> "FakeSpanCtx":
        rec = SpanRecord(name=name, attributes=dict(attrs))
        self.spans.append(rec)
        return FakeSpanCtx(rec)


class FakeSpanCtx:
    def __init__(self, rec: SpanRecord) -> None:
        self.rec = rec

    def __enter__(self) -> SpanRecord:
        return self.rec

    def __exit__(self, *_: Any) -> None:
        return None


# --------- M1: status-quo tools (mirrors current per-tool style) ---------


class M1EchoTool(Tool):
    @property
    def id(self) -> ToolID:
        return ToolID("m1_echo")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="m1_echo", description="echo", required=("text",))

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            text = kwargs["text"]
            return Result.ok(data=text)
        except KeyError as e:
            return Result.fail(error=f"Missing parameter: {e}")
        except Exception as e:
            return Result.fail(error=str(e))


class M1NoisyTool(Tool):
    """Returns a 50KB blob — no truncation today."""

    @property
    def id(self) -> ToolID:
        return ToolID("m1_noisy")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="m1_noisy", description="noise")

    async def execute(self, **kwargs: Any) -> ToolResult:
        return Result.ok(data="x" * 50_000)


class M1RaisingTool(Tool):
    @property
    def id(self) -> ToolID:
        return ToolID("m1_raise")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="m1_raise", description="raises")

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("boom")


# --------- M2: decorator wrapper applied at registration ---------


@dataclass(frozen=True)
class WrapperConfig:
    max_output_bytes: int = 2048
    tracer: FakeTracer | None = None


class WrappedTool(Tool):
    """Adapter that adds span + truncation + error capture around an inner Tool."""

    def __init__(self, inner: Tool, config: WrapperConfig) -> None:
        self._inner = inner
        self._cfg = config

    @property
    def id(self) -> ToolID:
        return self._inner.id

    @property
    def schema(self) -> ToolSchema:
        return self._inner.schema

    async def execute(self, **kwargs: Any) -> ToolResult:
        tracer = self._cfg.tracer
        ctx = (
            tracer.span("gen_ai.tool.execute", **{"tool.name": str(self.id)})
            if tracer
            else _NullCtx()
        )
        with ctx as span:
            t0 = time.perf_counter()
            try:
                result = await self._inner.validated_execute(**kwargs)
            except Exception as e:
                result = Result.fail(
                    error=str(e),
                    metadata={
                        "tool": str(self.id),
                        "error_code": "tool_exception",
                        "error_type": type(e).__name__,
                    },
                )
            result = self._truncate(result)
            if span is not None and hasattr(span, "attributes"):
                span.attributes["tool.duration_ms"] = (time.perf_counter() - t0) * 1000
                span.attributes["tool.success"] = result.success
                payload = result.data if result.success else result.error
                size = len(str(payload)) if payload is not None else 0
                span.attributes["tool.output_size_bytes"] = size
            return result

    def _truncate(self, result: ToolResult) -> ToolResult:
        if not result.success or result.data is None:
            return result
        text = str(result.data)
        if len(text) <= self._cfg.max_output_bytes:
            return result
        head = text[: self._cfg.max_output_bytes]
        meta = {**(result.metadata or {}), "truncated": True, "original_size": len(text)}
        return Result.ok(data=head, metadata=meta)


class _NullCtx:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: Any) -> None:
        return None


# --------- M2 user tools (no per-tool span/truncation/error capture) ---------


class M2EchoTool(Tool):
    @property
    def id(self) -> ToolID:
        return ToolID("m2_echo")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="m2_echo", description="echo", required=("text",))

    async def execute(self, **kwargs: Any) -> ToolResult:
        return Result.ok(data=kwargs["text"])


class M2NoisyTool(Tool):
    @property
    def id(self) -> ToolID:
        return ToolID("m2_noisy")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="m2_noisy", description="noise")

    async def execute(self, **kwargs: Any) -> ToolResult:
        return Result.ok(data="x" * 50_000)


class M2RaisingTool(Tool):
    @property
    def id(self) -> ToolID:
        return ToolID("m2_raise")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="m2_raise", description="raises")

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("boom")


# --------- M3: middleware chain ---------


NextFn = Callable[[], Awaitable[ToolResult]]


@dataclass
class ExecCtx:
    tool: Tool
    kwargs: dict[str, Any]
    span: SpanRecord | None = None


Middleware = Callable[[ExecCtx, NextFn], Awaitable[ToolResult]]


def span_middleware(tracer: FakeTracer | None) -> Middleware:
    async def mw(ctx: ExecCtx, nxt: NextFn) -> ToolResult:
        if tracer is None:
            return await nxt()
        with tracer.span("gen_ai.tool.execute", **{"tool.name": str(ctx.tool.id)}) as span:
            ctx.span = span
            t0 = time.perf_counter()
            res = await nxt()
            span.attributes["tool.duration_ms"] = (time.perf_counter() - t0) * 1000
            span.attributes["tool.success"] = res.success
            return res

    return mw


async def validation_middleware(ctx: ExecCtx, nxt: NextFn) -> ToolResult:
    missing = [r for r in ctx.tool.schema.required if r not in ctx.kwargs]
    if missing:
        return Result.fail(
            error=f"Missing required parameters: {', '.join(missing)}",
            metadata={"error_code": "validation_failed", "missing": missing},
        )
    return await nxt()


def truncate_middleware(max_bytes: int) -> Middleware:
    async def mw(ctx: ExecCtx, nxt: NextFn) -> ToolResult:
        res = await nxt()
        if not res.success or res.data is None:
            return res
        text = str(res.data)
        if len(text) <= max_bytes:
            return res
        return Result.ok(
            data=text[:max_bytes],
            metadata={**(res.metadata or {}), "truncated": True, "original_size": len(text)},
        )

    return mw


async def exception_middleware(ctx: ExecCtx, nxt: NextFn) -> ToolResult:
    try:
        return await nxt()
    except Exception as e:
        return Result.fail(
            error=str(e),
            metadata={"error_code": "tool_exception", "error_type": type(e).__name__},
        )


def chain(middlewares: list[Middleware]) -> Callable[[Tool], Tool]:
    def wrap(inner: Tool) -> Tool:
        class Chained(Tool):
            @property
            def id(self) -> ToolID:
                return inner.id

            @property
            def schema(self) -> ToolSchema:
                return inner.schema

            async def execute(self, **kwargs: Any) -> ToolResult:
                ctx = ExecCtx(tool=inner, kwargs=kwargs)

                async def terminal() -> ToolResult:
                    return await inner.execute(**kwargs)

                nxt: NextFn = terminal
                for mw in reversed(middlewares):
                    bound_mw, bound_nxt = mw, nxt

                    async def step(_mw=bound_mw, _nxt=bound_nxt) -> ToolResult:
                        return await _mw(ctx, _nxt)

                    nxt = step
                return await nxt()

        return Chained()

    return wrap


# --------- Bench ---------


async def time_n(coro_factory: Callable[[], Awaitable[Any]], n: int = 200) -> tuple[float, float]:
    samples_ms: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        await coro_factory()
        samples_ms.append((time.perf_counter() - t0) * 1000)
    samples_ms.sort()
    p50 = statistics.median(samples_ms)
    p99 = samples_ms[int(0.99 * len(samples_ms)) - 1]
    return p50, p99


async def main() -> None:
    # M1 — baseline
    m1_tracer = FakeTracer()  # never written to (no spans in M1 tools)
    m1_tools: list[Tool] = [M1EchoTool(), M1NoisyTool(), M1RaisingTool()]

    # M2 — wrapped at registration
    m2_tracer = FakeTracer()
    m2_cfg = WrapperConfig(max_output_bytes=2048, tracer=m2_tracer)
    m2_tools: list[Tool] = [WrappedTool(M2EchoTool(), m2_cfg), WrappedTool(M2NoisyTool(), m2_cfg), WrappedTool(M2RaisingTool(), m2_cfg)]

    # M3 — middleware chain
    m3_tracer = FakeTracer()
    chain_wrap = chain(
        [
            span_middleware(m3_tracer),
            exception_middleware,
            validation_middleware,
            truncate_middleware(2048),
        ]
    )
    m3_tools: list[Tool] = [chain_wrap(M2EchoTool()), chain_wrap(M2NoisyTool()), chain_wrap(M2RaisingTool())]

    findings: dict[str, Any] = {"M1": {}, "M2": {}, "M3": {}}

    for label, tools, tracer in [
        ("M1", m1_tools, m1_tracer),
        ("M2", m2_tools, m2_tracer),
        ("M3", m3_tools, m3_tracer),
    ]:
        results: list[ToolResult] = []
        echo, noisy, raising = tools
        results.append(await echo.execute(text="hi"))
        results.append(await echo.execute())  # missing required
        results.append(await noisy.execute())
        try:
            results.append(await raising.execute())
        except Exception as e:
            results.append(Result.fail(error=f"uncaught: {e}"))

        success = sum(1 for r in results if r.success)
        truncated = sum(1 for r in results if r.success and (r.metadata or {}).get("truncated"))
        validation_errors_uniform = (
            results[1].metadata is not None
            and "missing" in (results[1].metadata or {})
        )
        exception_caught = not results[3].success and "boom" in (results[3].error or "")

        # spans recorded
        span_count = len(tracer.spans)

        # perf
        p50_echo, p99_echo = await time_n(lambda: echo.execute(text="hi"), n=200)

        findings[label] = {
            "tool_count": len(tools),
            "spans_recorded": span_count,
            "span_coverage_pct": (span_count / 4) * 100 if span_count else 0,
            "noisy_output_chars": len(str(results[2].data)) if results[2].success else 0,
            "noisy_truncated": truncated > 0,
            "validation_metadata_present": validation_errors_uniform,
            "exception_caught_uniformly": exception_caught,
            "p50_ms": round(p50_echo, 4),
            "p99_ms": round(p99_echo, 4),
            "results": [
                {"success": r.success, "error": r.error, "metadata": r.metadata}
                for r in results
            ],
        }

    print(json.dumps(findings, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
