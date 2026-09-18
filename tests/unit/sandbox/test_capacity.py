"""Unit tests for SystemCapacity resource limits."""

import os
from unittest.mock import patch
import pytest

from cemaf.sandbox.capacity import SystemCapacity


@pytest.mark.unit
def test_system_capacity_snapshot() -> None:
    """SystemCapacity.snapshot returns a valid capacity snapshot."""
    capacity = SystemCapacity.snapshot()
    assert isinstance(capacity, SystemCapacity)
    assert capacity.available_memory_mb >= 0.0
    assert capacity.cpu_count >= 1
    assert capacity.cpu_load_avg >= 0.0
    assert capacity.disk_free_mb >= 0.0


@pytest.mark.unit
@pytest.mark.parametrize(
    "available_mem, fraction, expected_min",
    [
        (1024.0, 0.25, 256.0),
        (100.0, 0.25, 64.0),  # Clamped to minimum of 64MB
        (0.0, 0.25, 64.0),    # Clamped to minimum of 64MB
    ],
)
def test_memory_limit_mb(available_mem: float, fraction: float, expected_min: float) -> None:
    """memory_limit_mb allocates a safe fraction and enforces minimum boundary."""
    capacity = SystemCapacity(
        available_memory_mb=available_mem,
        cpu_count=4,
        cpu_load_avg=0.5,
        disk_free_mb=1024.0,
    )
    assert capacity.memory_limit_mb(fraction) == max(64.0, available_mem * fraction)


@pytest.mark.unit
@pytest.mark.parametrize(
    "load, mem, expected",
    [
        (0.5, 512.0, False),  # Normal load and plenty of memory
        (0.9, 512.0, True),   # CPU average normalized per-core load average > 0.8
        (0.5, 128.0, True),   # Available memory < 256 MB
        (0.9, 128.0, True),   # Both CPU and memory under pressure
    ],
)
def test_is_under_pressure(load: float, mem: float, expected: bool) -> None:
    """is_under_pressure returns True if the CPU or memory resources are strained."""
    capacity = SystemCapacity(
        available_memory_mb=mem,
        cpu_count=4,
        cpu_load_avg=load,
        disk_free_mb=1024.0,
    )
    assert capacity.is_under_pressure() is expected


@pytest.mark.unit
def test_system_capacity_snapshot_darwin_parsing() -> None:
    """SystemCapacity VM stat parsing works correctly on Darwin-like platforms."""
    with patch("platform.system", return_value="Darwin"), \
         patch("subprocess.run") as mock_run:
        
        # Mock sysctl and vm_stat outputs
        import sys
        from unittest.mock import MagicMock
        
        mock_sysctl = MagicMock()
        mock_sysctl.stdout = "8589934592\n"  # 8 GB
        
        mock_vmstat = MagicMock()
        mock_vmstat.stdout = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                   100000.
Pages inactive:                50000.
"""
        mock_run.side_effect = [mock_sysctl, mock_vmstat]
        
        capacity = SystemCapacity.snapshot()
        assert capacity.available_memory_mb == (150000 * 16384) / (1024 * 1024)


@pytest.mark.unit
def test_system_capacity_snapshot_linux_parsing() -> None:
    """SystemCapacity proc memory parsing works correctly on Linux-like platforms."""
    from unittest.mock import mock_open
    meminfo_content = """MemTotal:        8169348 kB
MemFree:         1048576 kB
MemAvailable:    2097152 kB
"""
    with patch("platform.system", return_value="Linux"), \
         patch("builtins.open", mock_open(read_data=meminfo_content)), \
         patch("os.cpu_count", return_value=4), \
         patch("os.getloadavg", return_value=(1.2, 0.8, 0.5)):
        
        capacity = SystemCapacity.snapshot()
        # MemAvailable: 2097152 kB -> 2048 MB
        assert capacity.available_memory_mb == 2048.0
        # normalized cpu_load_avg = load_avg[0] / cpu_count = 1.2 / 4 = 0.3
        assert capacity.cpu_count == 4
        assert capacity.cpu_load_avg == 0.3
