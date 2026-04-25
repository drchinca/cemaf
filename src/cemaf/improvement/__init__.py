"""
Improvement module — self-learning feedback loop for CEMAF.

Connects execution audits to strategy memory and trust tracking so the
framework gets better over time without manual tuning.
"""

from cemaf.improvement.loop import ExecutionSummary, ImprovementOutcome, SelfImprovementLoop

__all__ = ["SelfImprovementLoop", "ImprovementOutcome", "ExecutionSummary"]
