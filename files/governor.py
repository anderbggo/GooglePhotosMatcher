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


def inspect_folder_metrics(folder_path):
    """Fast folder scanner to compute exact file count and total size."""
    if not folder_path:
        return None
    try:
        from pathlib import Path
        folder = Path(folder_path).resolve()
        if not folder.is_dir():
            return None
        total_files = 0
        total_bytes = 0
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in {".git", ".gpm-scratch"}]
            for name in filenames:
                total_files += 1
                try:
                    total_bytes += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        gb = total_bytes / (1024 ** 3)
        mb = total_bytes / (1024 ** 2)
        size_str = f"{gb:.1f} GB" if gb >= 1.0 else f"{mb:.1f} MB"
        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "size_str": size_str,
        }
    except Exception:
        return None


def calculate_dynamic_eta(file_count, threads=None, ram_gb=None):
    """Calculate real-world processing time based on actual files and allocated threads."""
    if not file_count or file_count <= 0:
        return "0s"
    specs = get_hardware_specs()
    threads = threads or specs["cores"]
    # Base throughput per worker with stay_open ExifTool daemon: ~18 files/sec
    concurrency_efficiency = 0.88 if threads > 1 else 1.0
    throughput = max(15.0, (18.0 * threads * concurrency_efficiency))
    seconds = file_count / throughput
    if seconds < 60:
        return f"~{max(1, round(seconds))}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"~{minutes:.1f} mins"
    hours = minutes / 60
    return f"~{hours:.1f} hrs"


def get_hardware_note(language="en"):
    """Return a clean system hardware capability note."""
    specs = get_hardware_specs()
    if language == "es":
        specs["est_files"] = specs["est_files"].replace(",", ".")
    return text(language, "hardware_note", **specs)


def get_dynamic_folder_note(folder_path=None, threads=None, language="en"):
    """Generate dynamic folder metrics and real ETA based on selected folder and threads."""
    metrics = inspect_folder_metrics(folder_path)
    specs = get_hardware_specs()
    active_threads = threads or specs["cores"]
    if not metrics or metrics["total_files"] == 0:
        return get_hardware_note(language)
    eta = calculate_dynamic_eta(metrics["total_files"], threads=active_threads, ram_gb=specs["ram_gb"])
    total_files_formatted = f"{metrics['total_files']:,}"
    if language == "es":
        total_files_formatted = total_files_formatted.replace(",", ".")
    return text(
        language,
        "folder_dynamic_note",
        total_files=total_files_formatted,
        size_str=metrics["size_str"],
        eta=eta,
        threads=active_threads,
        ram_gb=specs["ram_gb"],
    )


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

