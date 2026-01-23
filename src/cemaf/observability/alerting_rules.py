"""
Recommended alerting rules for CEMAF metrics.

Provides a set of recommended alerting rules for common production scenarios.
Rules can be exported to Prometheus format for use with alerting systems.

Example:
    from cemaf.observability.alerting_rules import (
        RECOMMENDED_ALERTS,
        export_prometheus_rules
    )

    # Export to Prometheus format
    export_prometheus_rules("alerting_rules.yml")

    # Get specific alerts
    critical_alerts = [a for a in RECOMMENDED_ALERTS if a.severity == Severity.CRITICAL]
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Severity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    """Alert rule definition for monitoring systems."""

    name: str
    """Alert rule name (e.g., HighDAGFailureRate)"""

    metric: str
    """Prometheus metric expression"""

    condition: str
    """Comparison operator (>, <, ==, etc.)"""

    threshold: float
    """Threshold value"""

    duration: str
    """Alert duration (e.g., "5m", "1h")"""

    severity: Severity
    """Alert severity level"""

    description: str
    """Human-readable alert description"""

    remediation: str
    """Recommended remediation steps"""


# Recommended alerting rules for CEMAF
RECOMMENDED_ALERTS = [
    # Error Rate Alerts
    AlertRule(
        name="HighDAGFailureRate",
        metric="rate(cemaf_dag_executions_failed[5m]) / rate(cemaf_dag_executions_total[5m])",
        condition=">",
        threshold=0.05,
        duration="5m",
        severity=Severity.WARNING,
        description="DAG failure rate exceeds 5% over 5 minutes",
        remediation="Check logs for error patterns. Review recent DAG changes. Verify dependency health.",
    ),
    AlertRule(
        name="CriticalDAGFailureRate",
        metric="rate(cemaf_dag_executions_failed[5m]) / rate(cemaf_dag_executions_total[5m])",
        condition=">",
        threshold=0.20,
        duration="5m",
        severity=Severity.CRITICAL,
        description="DAG failure rate exceeds 20% over 5 minutes",
        remediation="IMMEDIATE: Check health dashboard. Review circuit breaker status. Escalate to on-call.",
    ),
    # Latency Alerts
    AlertRule(
        name="HighDAGLatencyP99",
        metric="histogram_quantile(0.99, cemaf_dag_duration_ms)",
        condition=">",
        threshold=30000,
        duration="10m",
        severity=Severity.WARNING,
        description="P99 DAG execution latency exceeds 30 seconds",
        remediation="Check node execution times. Review LLM latency. Check for slow database queries.",
    ),
    AlertRule(
        name="HighLLMLatencyP95",
        metric="histogram_quantile(0.95, cemaf_llm_latency_ms)",
        condition=">",
        threshold=10000,
        duration="5m",
        severity=Severity.WARNING,
        description="P95 LLM latency exceeds 10 seconds",
        remediation="Check LLM provider status. Review prompt sizes. Consider rate limiting.",
    ),
    # Circuit Breaker Alerts
    AlertRule(
        name="CircuitBreakerOpen",
        metric="cemaf_circuit_breaker_state",
        condition="==",
        threshold=1,  # OPEN state
        duration="2m",
        severity=Severity.CRITICAL,
        description="Circuit breaker has been open for 2+ minutes",
        remediation="Check downstream service health. Review failure logs. Consider manual intervention.",
    ),
    # Rate Limiting Alerts
    AlertRule(
        name="HighRateLimitRejections",
        metric="rate(cemaf_rate_limiter_requests_rejected[5m]) / rate(cemaf_rate_limiter_requests_total[5m])",
        condition=">",
        threshold=0.10,
        duration="5m",
        severity=Severity.WARNING,
        description="Rate limiter rejecting >10% of requests",
        remediation="Review rate limit configuration. Check for traffic spikes. Consider increasing limits.",
    ),
    # Cost Alerts
    AlertRule(
        name="HighLLMCostRate",
        metric="rate(cemaf_llm_cost_total_cents[1h])",
        condition=">",
        threshold=10000,
        duration="15m",
        severity=Severity.WARNING,
        description="LLM costs exceeding $100/hour",
        remediation="Review token usage patterns. Check for runaway generations. Verify prompt optimization.",
    ),
    AlertRule(
        name="DailyLLMCostBudget",
        metric="sum_over_time(cemaf_llm_cost_total_cents[24h])",
        condition=">",
        threshold=240000,
        duration="0m",
        severity=Severity.CRITICAL,
        description="Daily LLM cost budget exceeded ($2400)",
        remediation="IMMEDIATE: Review cost breakdown by model. Implement emergency cost controls.",
    ),
    # Cache Performance Alerts
    AlertRule(
        name="LowCacheHitRate",
        metric="cemaf_cache_hit_rate",
        condition="<",
        threshold=0.50,
        duration="30m",
        severity=Severity.WARNING,
        description="Cache hit rate below 50% for 30 minutes",
        remediation="Review cache key generation. Check TTL settings. Verify cache size limits.",
    ),
    # Health Check Alerts
    AlertRule(
        name="CriticalDependencyUnhealthy",
        metric="cemaf_health_status{critical='true'}",
        condition="==",
        threshold=2,
        duration="1m",
        severity=Severity.CRITICAL,
        description="Critical dependency unhealthy",
        remediation="Check component health logs. Verify connectivity. Escalate immediately.",
    ),
    # Token Usage Alerts
    AlertRule(
        name="HighTokenUsageRate",
        metric="rate(cemaf_llm_tokens_total[5m])",
        condition=">",
        threshold=1000000,
        duration="5m",
        severity=Severity.WARNING,
        description="Token consumption exceeds 1M tokens per 5 minutes",
        remediation="Review active DAGs. Check for prompt inflation. Verify no runaway recursion.",
    ),
    # Retry Alerts
    AlertRule(
        name="HighRetryExhaustionRate",
        metric="rate(cemaf_retry_exhausted[5m]) / rate(cemaf_retry_attempts[5m])",
        condition=">",
        threshold=0.20,
        duration="10m",
        severity=Severity.WARNING,
        description="More than 20% of retries exhausted",
        remediation="Check failure patterns. Review retry configuration. Investigate root cause.",
    ),
]


def export_prometheus_rules(output_file: str | Path) -> None:
    """
    Export alerting rules to Prometheus format.

    Generates a prometheus alerting rules file that can be used with Prometheus
    or compatible monitoring systems.

    Args:
        output_file: Path to write the rules file

    Example:
        export_prometheus_rules("alerting_rules.yml")

        # Result: Standard Prometheus alerting rules YAML file
    """
    output_path = Path(output_file)

    with open(output_path, "w") as f:
        f.write("# CEMAF Recommended Alerting Rules\n")
        f.write("# Generated from cemaf.observability.alerting_rules\n")
        f.write("# For use with Prometheus or compatible monitoring systems\n")
        f.write("\n")
        f.write("groups:\n")
        f.write("  - name: cemaf_alerts\n")
        f.write("    interval: 30s\n")
        f.write("    rules:\n")

        for rule in RECOMMENDED_ALERTS:
            f.write(f"      - alert: {rule.name}\n")
            f.write(f"        expr: {rule.metric} {rule.condition} {rule.threshold}\n")
            f.write(f"        for: {rule.duration}\n")
            f.write("        labels:\n")
            f.write(f"          severity: {rule.severity.value}\n")
            f.write("        annotations:\n")
            f.write(f"          summary: {rule.description}\n")
            f.write(f"          remediation: {rule.remediation}\n")
            f.write("\n")


def get_alerts_by_severity(severity: Severity) -> list[AlertRule]:
    """
    Get all alerts of a specific severity level.

    Args:
        severity: Severity level to filter by

    Returns:
        List of matching alert rules

    Example:
        critical_alerts = get_alerts_by_severity(Severity.CRITICAL)
        for alert in critical_alerts:
            print(f"Critical alert: {alert.name}")
    """
    return [a for a in RECOMMENDED_ALERTS if a.severity == severity]


def get_alert_by_name(name: str) -> AlertRule | None:
    """
    Get a specific alert by name.

    Args:
        name: Alert name

    Returns:
        AlertRule if found, None otherwise

    Example:
        alert = get_alert_by_name("HighDAGFailureRate")
        if alert:
            print(f"Threshold: {alert.threshold}")
    """
    for alert in RECOMMENDED_ALERTS:
        if alert.name == name:
            return alert
    return None
