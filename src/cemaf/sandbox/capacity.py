"""Read live system stats to determine safe sandbox resource limits."""

import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemCapacity:
    """Point-in-time snapshot of available system resources."""

    available_memory_mb: float  # Available RAM in MB
    cpu_count: int  # Logical CPU cores
    cpu_load_avg: float  # 1-min load average (0.0-1.0 per core)
    disk_free_mb: float  # Free disk in MB (for temp files)

    @classmethod
    def snapshot(cls) -> SystemCapacity:
        """Take a live snapshot of available system resources."""
        import platform

        if platform.system() == "Darwin":
            # macOS: use sysctl for total memory, vm_stat for free pages
            mem_result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
            )
            try:
                _total_bytes = int(mem_result.stdout.strip())
            except ValueError:
                _total_bytes = 0

            vm_result = subprocess.run(
                ["vm_stat"],
                capture_output=True,
                text=True,
            )
            # Apple Silicon uses 16 KiB pages; Intel uses 4 KiB.
            # Read the page size from the header line when available.
            page_size = 16384  # safe default for Apple Silicon
            free_pages = 0
            for line in vm_result.stdout.splitlines():
                if "page size of" in line:
                    # e.g. "Mach Virtual Memory Statistics: (page size of 16384 bytes)"
                    parts = line.split("page size of")
                    if len(parts) == 2:
                        try:
                            page_size = int(parts[1].split()[0])
                        except ValueError, IndexError:
                            pass
                if "Pages free" in line or "Pages inactive" in line:
                    raw = line.split(":")[1].strip().rstrip(".")
                    try:
                        free_pages += int(raw)
                    except ValueError:
                        pass
            available_mb = (free_pages * page_size) / (1024 * 1024)
        else:
            # Linux: parse /proc/meminfo
            try:
                with open("/proc/meminfo") as f:
                    info: dict[str, int] = {}
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            info[parts[0].strip()] = int(parts[1].strip().split()[0])
                available_mb = info.get("MemAvailable", info.get("MemFree", 0)) / 1024
            except OSError:
                available_mb = 512.0  # safe fallback

        cpu_count = os.cpu_count() or 1
        try:
            load_avg = os.getloadavg()[0] / cpu_count  # normalise per core
        except OSError:
            load_avg = 0.0

        # Disk: check /tmp (falls back to cwd on Windows-like environments)
        try:
            stat = os.statvfs("/tmp")
            disk_free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
        except OSError, AttributeError:
            disk_free_mb = 1024.0  # safe fallback

        return cls(
            available_memory_mb=available_mb,
            cpu_count=cpu_count,
            cpu_load_avg=load_avg,
            disk_free_mb=disk_free_mb,
        )

    def memory_limit_mb(self, fraction: float = 0.25) -> float:
        """Allocate a safe fraction of available memory to the sandbox.

        Always returns at least 64 MB regardless of system state.
        """
        return max(64.0, self.available_memory_mb * fraction)

    def is_under_pressure(self) -> bool:
        """True if the system is already under load — be more conservative."""
        return self.cpu_load_avg > 0.8 or self.available_memory_mb < 256
