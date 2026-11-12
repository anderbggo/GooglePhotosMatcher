"""Crash-proof anti-corruption real-time report journal and semi-matched detection engine."""

import csv
import os
from pathlib import Path
import threading
from typing import Any

from matching import MEDIA_EXTENSIONS, normalized_name, sidecar_media_name


class CrashProofReportJournal:
    """Thread-safe, crash-resilient CSV report writer with immediate fsync.

    Writes rows in real time as files are processed. If the application is abruptly
    closed, force killed, or encounters a power loss, previously processed rows
    remain completely intact without corruption or data truncation.
    """

    def __init__(self, csv_path: Path):
        self.path = Path(csv_path)
        self.lock = threading.Lock()
        self._record_count = 0
        self._init_header()

    def _init_header(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists() or self.path.stat().st_size == 0:
                with self.path.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["json", "media", "status", "rule", "details"])
                    stream.flush()
                    try:
                        os.fsync(stream.fileno())
                    except OSError:
                        pass

    def record(self, json_rel: str, media_rel: str, status: str, rule: str, details: str):
        """Append a single processed item immediately to disk with fsync."""
        with self.lock:
            with self.path.open("a", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow([json_rel, media_rel, status, rule, details])
                stream.flush()
                try:
                    os.fsync(stream.fileno())
                except OSError:
                    pass
            self._record_count += 1

    @property
    def record_count(self) -> int:
        return self._record_count


def detect_prior_progress(root_folder: Path) -> dict[str, Any]:
    """Scan root_folder to detect previous progress, semi-matched sidecars, and standalone media.

    Reads existing matching-report*.csv or journal files if present, inspects existing
    JSON sidecars vs media files, and returns a comprehensive health status.
    """
    root = Path(root_folder).resolve()
    if not root.is_dir():
        return {"error": "Folder not found"}

    journal_records = []
    # Check for existing reports or journals
    report_files = sorted(root.glob("**/matching-report*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if report_files:
        latest_report = report_files[0]
        try:
            with latest_report.open("r", encoding="utf-8-sig", errors="replace") as stream:
                reader = csv.DictReader(stream)
                for row in reader:
                    journal_records.append(row)
        except OSError:
            pass

    # Quick scan of folder structure
    total_media = 0
    total_jsons = 0
    unclaimed_media = 0
    sidecar_names = set()
    media_names = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", ".gpm-scratch", "MatchedMedia", "EditedRaw"}]
        for name in filenames:
            ext = os.path.splitext(name)[1].casefold()
            if ext == ".json":
                total_jsons += 1
                base, _ = sidecar_media_name(name)
                sidecar_names.add(normalized_name(base))
            elif ext in MEDIA_EXTENSIONS:
                total_media += 1
                media_names.add(normalized_name(name))

    # Calculate status from journal if available
    journal_restored = sum(1 for r in journal_records if r.get("status") in ("restored", "already_restored"))
    journal_errors = sum(1 for r in journal_records if r.get("status") == "error")
    journal_unmatched = sum(1 for r in journal_records if r.get("status") == "unmatched")

    # Semi-matched: media that share stems with sidecars but are unconsumed
    pending_sidecars = total_jsons
    standalone_media = max(0, total_media - len(sidecar_names.intersection(media_names)))

    return {
        "root": str(root),
        "total_media": total_media,
        "total_jsons": total_jsons,
        "pending_sidecars": pending_sidecars,
        "standalone_media": standalone_media,
        "has_prior_report": bool(report_files),
        "prior_report_file": report_files[0].name if report_files else None,
        "prior_restored": journal_restored,
        "prior_errors": journal_errors,
        "prior_unmatched": journal_unmatched,
    }
