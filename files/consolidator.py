"""Multi-part Google Takeout consolidation and album unification engine."""

import hashlib
import os
from pathlib import Path
import shutil
import re

TAKEOUT_DIR_PATTERNS = (
    re.compile(r"^takeout.*", re.IGNORECASE),
    re.compile(r".*part.*", re.IGNORECASE),
    re.compile(r".*google.*takeout.*", re.IGNORECASE),
)

GOOGLE_PHOTOS_SUBDIRS = (
    "Google Photos",
    "Fotos de Google Fotos",
    "Google Fotos",
    "Photos",
)


def is_takeout_partition(directory: Path) -> bool:
    """Return True if directory represents a Google Takeout partition."""
    if not directory.is_dir():
        return False
    name = directory.name.lower()
    for pattern in TAKEOUT_DIR_PATTERNS:
        if pattern.match(name):
            return True
    for sub in GOOGLE_PHOTOS_SUBDIRS:
        if (directory / sub).is_dir() or (directory / "Takeout" / sub).is_dir():
            return True
    return False


def find_takeout_partitions(root_folder: Path) -> list[Path]:
    """Find all sibling Takeout partition directories under root_folder."""
    root = Path(root_folder).resolve()
    if not root.is_dir():
        return []

    partitions = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return []

    for entry in entries:
        if entry.is_dir() and not entry.name.startswith((".", "MatchedMedia", "EditedRaw", "Takeout_Consolidated")):
            if is_takeout_partition(entry):
                partitions.append(entry)

    return partitions


def get_partition_base(partition: Path) -> Path:
    """Resolve the effective media root inside a Takeout partition."""
    for sub in GOOGLE_PHOTOS_SUBDIRS:
        direct = partition / sub
        if direct.is_dir():
            return direct
        nested = partition / "Takeout" / sub
        if nested.is_dir():
            return nested
    if (partition / "Takeout").is_dir():
        return partition / "Takeout"
    return partition


def _file_quick_hash(path: Path) -> tuple[int, bytes]:
    """Return file size and a 4KB sample hash for quick collision deduplication."""
    try:
        stat = path.stat()
        size = stat.st_size
        with path.open("rb") as f:
            sample = f.read(4096)
        return size, hashlib.md5(sample).digest()
    except OSError:
        return -1, b""


def _get_unique_target_path(target: Path) -> Path:
    """Generate a numbered filename if target already exists with different content."""
    if not target.exists():
        return target

    directory = target.parent
    stem = target.stem
    suffix = target.suffix

    # Special handling for .json sidecars with compound extensions e.g. .jpg.json
    if suffix.lower() == ".json":
        inner_path = Path(stem)
        if inner_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov", ".gif", ".dng"):
            base_stem = inner_path.stem
            media_suffix = inner_path.suffix
            counter = 1
            while True:
                candidate = directory / f"{base_stem}({counter}){media_suffix}.json"
                if not candidate.exists():
                    return candidate
                counter += 1

    counter = 1
    while True:
        candidate = directory / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def consolidate_takeout_partitions(root_folder: Path, window=None, cancel_event=None) -> Path:
    """Consolidate multiple Takeout partitions into a single unified directory structure.

    Combines split albums (e.g. 'Photos from 2020' split across Part 01 and Part 02),
    couples media files with their matching JSON sidecars, and resolves collisions safely.
    Returns the Path to the consolidated folder (or original root if no multi-parts found).
    """
    root = Path(root_folder).resolve()
    partitions = find_takeout_partitions(root)

    if len(partitions) <= 1:
        return root

    def log(message):
        if window is not None:
            try:
                window.write_event_value("-LOG-", message)
            except Exception:
                pass

    dest_dir = root / "Takeout_Consolidated"
    dest_dir.mkdir(exist_ok=True)

    log(f"Takeout consolidation started: merging {len(partitions)} parts into {dest_dir.name}")

    total_moved = 0
    total_skipped_dup = 0
    # Map of (source_parent, source_filename) -> renamed_dest_stem_for_sidecar
    rename_map = {}

    for part_idx, part in enumerate(partitions, start=1):
        if cancel_event is not None and cancel_event.is_set():
            log("Takeout consolidation cancelled")
            return dest_dir

        base = get_partition_base(part)
        log(f"Scanning partition {part_idx}/{len(partitions)}: {part.name}")

        try:
            all_files = sorted(base.rglob("*"), key=lambda p: (p.suffix.lower() == ".json", p.name.casefold()))
        except OSError:
            continue

        for source_file in all_files:
            if cancel_event is not None and cancel_event.is_set():
                break
            if not source_file.is_file():
                continue

            try:
                rel_path = source_file.relative_to(base)
            except ValueError:
                rel_path = Path(source_file.name)

            dest_file = dest_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            # Check if matching media was renamed previously
            if source_file.suffix.lower() == ".json":
                # Check if corresponding media had collision rename
                media_key = (source_file.parent, source_file.stem)
                if media_key in rename_map:
                    new_stem = rename_map[media_key]
                    dest_file = dest_file.parent / f"{new_stem}.json"

            if dest_file.exists():
                src_size, src_sample = _file_quick_hash(source_file)
                dst_size, dst_sample = _file_quick_hash(dest_file)
                if src_size == dst_size and src_sample == dst_sample and src_size > 0:
                    # Identical file already consolidated from an earlier partition
                    total_skipped_dup += 1
                    continue
                else:
                    # Content collision: assign unique numbered name
                    new_dest_file = _get_unique_target_path(dest_file)
                    if source_file.suffix.lower() != ".json":
                        rename_map[(source_file.parent, source_file.name)] = new_dest_file.name
                    dest_file = new_dest_file

            try:
                # Fast atomic move on the same filesystem; fallback to copy+delete
                shutil.move(str(source_file), str(dest_file))
                total_moved += 1
            except OSError:
                try:
                    shutil.copy2(str(source_file), str(dest_file))
                    source_file.unlink(missing_ok=True)
                    total_moved += 1
                except OSError:
                    pass

    log(f"Takeout consolidation complete: {total_moved} files consolidated, {total_skipped_dup} identical duplicates skipped")
    return dest_dir

