"""Interceptor spine (SPEC-01a) — the PRE→execute→POST chain every AGENT node passes through.

Turns capabilities from bolt-on executor branches into stations on one ordered
chain. Empty pipeline is a no-op (additive). The first station, GateEvalInterceptor,
makes a quality gate genuinely block downstream nodes.
"""

from cemaf.interceptors.gate_eval import GateEvalInterceptor
from cemaf.interceptors.pipeline import InterceptorPipeline, create_interceptor_pipeline
from cemaf.interceptors.protocols import Interceptor, PostInterceptor, PreInterceptor
from cemaf.interceptors.types import (
    DecisionKind,
    PostflightDecision,
    PreflightDecision,
)

__all__ = [
    "DecisionKind",
    "GateEvalInterceptor",
    "Interceptor",
    "InterceptorPipeline",
    "PostInterceptor",
    "PostflightDecision",
    "PreInterceptor",
    "PreflightDecision",
    "create_interceptor_pipeline",
]
