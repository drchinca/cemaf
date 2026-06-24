"""
Improvement module — self-learning feedback loop for CEMAF.

Connects execution audits to strategy memory and trust tracking so the
framework gets better over time without manual tuning.
"""

from cemaf.improvement.export import (
    ImprovementReportBundle,
    ImprovementRunReport,
    build_improvement_run_report,
    compose_improvement_label,
    export_improvement_report,
)
from cemaf.improvement.factories import (
    ImprovementRuntime,
    create_improvement_runtime,
    create_self_improvement_loop,
    create_strategy_memory,
    create_trust_ledger,
)
from cemaf.improvement.loop import ExecutionSummary, ImprovementOutcome, SelfImprovementLoop

__all__ = [
    "ExecutionSummary",
    "ImprovementRuntime",
    "ImprovementOutcome",
    "ImprovementReportBundle",
    "ImprovementRunReport",
    "SelfImprovementLoop",
    "build_improvement_run_report",
    "create_improvement_runtime",
    "create_self_improvement_loop",
    "create_strategy_memory",
    "create_trust_ledger",
    "compose_improvement_label",
    "export_improvement_report",
]
