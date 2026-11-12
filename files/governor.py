"""Hardware intelligence and adaptive resource governance for enterprise workloads."""

import gc
import os
import platform
import time
from translations import text

try:
    import psutil
except ImportError:
    psutil = None


def get_hardware_specs():
    """Detect system CPU cores, RAM, and calculate realistic throughput estimates."""
    cores = os.cpu_count() or 4
    physical_cores = cores
    ram_bytes = 8 * (1024 ** 3)  # default 8 GB fallback

    if psutil is not None:
        try:
            cores = psutil.cpu_count(logical=True) or cores
            physical_cores = psutil.cpu_count(logical=False) or cores
            ram_bytes = psutil.virtual_memory().total
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_bytes = stat.ullTotalPhys
        except Exception:
            pass

    ram_gb = max(2, round(ram_bytes / (1024 ** 3)))

    # Real-world benchmark rate:
    # Single-thread ExifTool writes ~15-20 files/sec on SSD.
    # Scaled concurrency factor bounded by storage I/O and ExifTool Perl daemon throughput.
    rate = min(60, 15 + min(cores, 16) * 2.5)
    est_files = int(round((rate * 18 * 60) / 500) * 500)
    est_gb = max(5, int(round(est_files * 0.005)))
    est_min = 18

    return {
        "cores": cores,
        "physical_cores": physical_cores,
        "ram_gb": ram_gb,
        "est_gb": est_gb,
        "est_files": f"{est_files:,}",
        "est_min": est_min,
    }


def get_hardware_note(language="en"):
    """Return a formatted hardware capability and throughput estimate note."""
    specs = get_hardware_specs()
    if language == "es":
        specs["est_files"] = specs["est_files"].replace(",", ".")
    return text(language, "hardware_note", **specs)


class AdaptiveGovernor:
    """Enterprise-grade resource governor that auto-scales processing intensity.

    Monitors host CPU utilization to throttle down (micro-yield) during peak user
    activity, scale up when CPU is idle, and govern RAM via periodic garbage collection.
    """

    def __init__(self, check_every=25, gc_every=2500):
        self.check_every = check_every
        self.gc_every = gc_every
        self.op_count = 0
        self.sleep_seconds = 0.0
        self.mode = "burst"
        self._last_check = 0.0

        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)  # seed initial measurement
            except Exception:
                pass

    def govern(self):
        """Invoke before/after batch file operations to maintain host responsiveness."""
        self.op_count += 1

        # Memory governance: periodic collection prevents RAM ballooning on 100k+ file scans
        if self.op_count % self.gc_every == 0:
            gc.collect()

        now = time.monotonic()
        if self.op_count % self.check_every == 0 or (now - self._last_check) > 2.0:
            self._last_check = now
            if psutil is not None:
                try:
                    cpu = psutil.cpu_percent(interval=None)
                    if cpu > 70.0:
                        # High user activity: enter gentle mode with micro-yield
                        self.mode = "gentle"
                        self.sleep_seconds = 0.012
                    elif cpu < 40.0:
                        # Idle machine: burst mode (full speed)
                        self.mode = "burst"
                        self.sleep_seconds = 0.0
                    else:
                        self.mode = "normal"
                        self.sleep_seconds = 0.002
                except Exception:
                    self.sleep_seconds = 0.0

        if self.sleep_seconds > 0.0:
            time.sleep(self.sleep_seconds)

