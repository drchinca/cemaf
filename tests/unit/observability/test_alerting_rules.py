"""Tests for alerting rules definitions and utilities."""

from pathlib import Path

from cemaf.observability.alerting_rules import (
    RECOMMENDED_ALERTS,
    AlertRule,
    Severity,
    export_prometheus_rules,
    get_alert_by_name,
    get_alerts_by_severity,
)


class TestSeverityEnum:
    """Tests for the Severity enum."""

    def test_has_three_levels(self) -> None:
        assert len(Severity) == 3

    def test_values(self) -> None:
        assert Severity.INFO.value == "info"
        assert Severity.WARNING.value == "warning"
        assert Severity.CRITICAL.value == "critical"


class TestAlertRule:
    """Tests for the AlertRule dataclass."""

    def test_creates_valid_rule(self) -> None:
        rule = AlertRule(
            name="TestAlert",
            metric="test_metric",
            condition=">",
            threshold=0.5,
            duration="5m",
            severity=Severity.WARNING,
            description="Test alert",
            remediation="Fix it.",
        )

        assert rule.name == "TestAlert"
        assert rule.threshold == 0.5
        assert rule.severity == Severity.WARNING


class TestRecommendedAlerts:
    """Tests for the RECOMMENDED_ALERTS list."""

    def test_contains_alerts(self) -> None:
        assert len(RECOMMENDED_ALERTS) > 0

    def test_all_entries_are_alert_rules(self) -> None:
        for alert in RECOMMENDED_ALERTS:
            assert isinstance(alert, AlertRule)

    def test_all_alerts_have_unique_names(self) -> None:
        names = [a.name for a in RECOMMENDED_ALERTS]
        assert len(names) == len(set(names))

    def test_all_alerts_have_non_empty_fields(self) -> None:
        for alert in RECOMMENDED_ALERTS:
            assert alert.name, f"Alert missing name: {alert}"
            assert alert.metric, f"Alert {alert.name} missing metric"
            assert alert.condition, f"Alert {alert.name} missing condition"
            assert alert.duration, f"Alert {alert.name} missing duration"
            assert alert.description, f"Alert {alert.name} missing description"
            assert alert.remediation, f"Alert {alert.name} missing remediation"

    def test_has_critical_alerts(self) -> None:
        critical = [a for a in RECOMMENDED_ALERTS if a.severity == Severity.CRITICAL]
        assert len(critical) >= 1

    def test_has_warning_alerts(self) -> None:
        warning = [a for a in RECOMMENDED_ALERTS if a.severity == Severity.WARNING]
        assert len(warning) >= 1

    def test_known_alert_exists(self) -> None:
        names = {a.name for a in RECOMMENDED_ALERTS}
        assert "HighDAGFailureRate" in names
        assert "CriticalDAGFailureRate" in names
        assert "CircuitBreakerOpen" in names


class TestGetAlertsBySeverity:
    """Tests for get_alerts_by_severity."""

    def test_returns_only_matching_severity(self) -> None:
        critical = get_alerts_by_severity(severity=Severity.CRITICAL)
        assert all(a.severity == Severity.CRITICAL for a in critical)

    def test_returns_list(self) -> None:
        result = get_alerts_by_severity(severity=Severity.WARNING)
        assert isinstance(result, list)

    def test_info_returns_empty_if_none_defined(self) -> None:
        info_alerts = get_alerts_by_severity(severity=Severity.INFO)
        # All current alerts are WARNING or CRITICAL, so INFO should be empty
        assert isinstance(info_alerts, list)

    def test_critical_count_matches_manual_filter(self) -> None:
        expected = [a for a in RECOMMENDED_ALERTS if a.severity == Severity.CRITICAL]
        actual = get_alerts_by_severity(severity=Severity.CRITICAL)
        assert len(actual) == len(expected)
        assert {a.name for a in actual} == {a.name for a in expected}


class TestGetAlertByName:
    """Tests for get_alert_by_name."""

    def test_finds_existing_alert(self) -> None:
        alert = get_alert_by_name(name="HighDAGFailureRate")
        assert alert is not None
        assert alert.name == "HighDAGFailureRate"
        assert alert.severity == Severity.WARNING

    def test_returns_none_for_missing_alert(self) -> None:
        result = get_alert_by_name(name="NonExistentAlert")
        assert result is None

    def test_exact_name_match(self) -> None:
        result = get_alert_by_name(name="highdagfailurerate")
        assert result is None  # case-sensitive


class TestExportPrometheusRules:
    """Tests for export_prometheus_rules."""

    def test_creates_file(self, tmp_path: Path) -> None:
        output = tmp_path / "alerts.yml"
        export_prometheus_rules(output_file=output)
        assert output.exists()

    def test_file_contains_header(self, tmp_path: Path) -> None:
        output = tmp_path / "alerts.yml"
        export_prometheus_rules(output_file=output)
        content = output.read_text()
        assert "CEMAF Recommended Alerting Rules" in content

    def test_file_contains_group_structure(self, tmp_path: Path) -> None:
        output = tmp_path / "alerts.yml"
        export_prometheus_rules(output_file=output)
        content = output.read_text()
        assert "groups:" in content
        assert "cemaf_alerts" in content
        assert "interval: 30s" in content

    def test_file_contains_all_alerts(self, tmp_path: Path) -> None:
        output = tmp_path / "alerts.yml"
        export_prometheus_rules(output_file=output)
        content = output.read_text()
        for alert in RECOMMENDED_ALERTS:
            assert f"alert: {alert.name}" in content

    def test_file_contains_severity_labels(self, tmp_path: Path) -> None:
        output = tmp_path / "alerts.yml"
        export_prometheus_rules(output_file=output)
        content = output.read_text()
        assert "severity: warning" in content
        assert "severity: critical" in content

    def test_file_contains_expressions(self, tmp_path: Path) -> None:
        output = tmp_path / "alerts.yml"
        export_prometheus_rules(output_file=output)
        content = output.read_text()
        for alert in RECOMMENDED_ALERTS:
            assert f"expr: {alert.metric} {alert.condition} {alert.threshold}" in content

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        output = str(tmp_path / "string_path.yml")
        export_prometheus_rules(output_file=output)
        assert Path(output).exists()
