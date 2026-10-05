import csv
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from auxFunctions import (
    IMAGE_EXTENSIONS,
    MediaMatcher,
    VIDEO_EXTENSIONS,
    exiftool_batch,
    get_content_identifier,
    normalized_name,
    set_image_metadata,
    set_photo_metadata,
    set_video_metadata,
    setWindowsTime,
    sidecar_media_name,
)


def log(window, msg):
    window.write_event_value("-LOG-", msg)
    print(msg)


def _metadata(data):
    timestamp = None
    for key in ("photoTakenTime", "photoLastModifiedTime"):
        value = data.get(key)
        if isinstance(value, dict) and value.get("timestamp") is not None:
            raw_timestamp = value["timestamp"]
            if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (str, int)):
                raise ValueError("Invalid photo timestamp")
            timestamp = int(raw_timestamp)
            datetime.fromtimestamp(timestamp)
            break
    if timestamp is None:
        raise ValueError("Missing photo timestamp")
    coordinates = (0.0, 0.0, 0.0)
    for key in ("geoData", "geoDataExif"):
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Invalid {key}")
        coordinates = tuple(float(value.get(field, 0) or 0) for field in ("latitude", "longitude", "altitude"))
        latitude, longitude, altitude = coordinates
        if not all(math.isfinite(number) for number in coordinates) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Invalid GPS coordinates")
        if latitude != 0 or longitude != 0:
            break
    description = data.get("description") or ""
    if not isinstance(description, str):
        raise ValueError("Invalid description")
    return {"timestamp": timestamp, "latitude": coordinates[0], "longitude": coordinates[1], "altitude": coordinates[2], "description": description}


def _scan_error(error):
    raise error


def _plan(root, edited_word, window, cancel_event):
    tasks = []
    matchers = {}
    for directory, subdirectories, filenames in os.walk(root, onerror=_scan_error, followlinks=False):
        folder = Path(directory)
        subdirectories[:] = sorted(name for name in subdirectories if name not in {"MatchedMedia", "EditedRaw"} and not (folder / name).is_symlink())
        filenames = sorted(name for name in filenames if not (folder / name).is_symlink())
        matcher = MediaMatcher(folder, filenames)
        matchers[folder] = matcher
        json_names = [name for name in filenames if name.casefold().endswith(".json")]
        sidecar_owners = defaultdict(set)
        for name in json_names:
            sidecar_owners[normalized_name(sidecar_media_name(name)[0])].add(name)
        for json_name in json_names:
            if cancel_event is not None and cancel_event.is_set():
                return tasks, matchers
            json_path = folder / json_name
            task = {"json": str(json_path.relative_to(root)), "media": "", "status": "pending", "rule": "", "details": "", "json_path": json_path, "json_paths": [json_path], "source": None, "raw": None, "companion": None}
            tasks.append(task)
            window.write_event_value("-UPDATE_PROGRESS-", (0, f"Scanning: {json_path.name}"))
            try:
                with json_path.open(encoding="utf-8-sig") as stream:
                    data = json.load(stream)
                if not isinstance(data, dict):
                    raise ValueError("JSON metadata must be an object")
                title = data.get("title")
                if not title or not any(key in data for key in ("photoTakenTime", "photoLastModifiedTime")):
                    task.update(status="skipped", details="Not a photo/video metadata sidecar")
                    continue
                if not isinstance(title, str):
                    raise ValueError("Invalid JSON title")
                task["metadata"] = _metadata(data)
                edited, original = matcher.match(title, json_name, edited_word)
                original_with_separate_edit = False
                if edited and sidecar_owners.get(normalized_name(edited), set()) - {json_name}:
                    original_with_separate_edit = original is not None
                    edited = None
                selected = edited or original
                if not selected:
                    task.update(status="error", details=f"No unambiguous media match for {title}")
                    continue
                task.update(source=folder / selected, media=str((folder / selected).relative_to(root)), rule=matcher.last_rule)
                if original_with_separate_edit:
                    task["output_folder"] = "EditedRaw"
                if edited and original and edited != original:
                    task["raw"] = folder / original
            except (OSError, ValueError, TypeError, OverflowError) as error:
                task.update(status="error", details=str(error))

    claims = defaultdict(list)
    for task in tasks:
        if task["status"] == "pending":
            claims[task["source"]].append(task)
    for source, owners in claims.items():
        if len(owners) < 2:
            continue
        if all(owner["metadata"] == owners[0]["metadata"] for owner in owners):
            for owner in owners[1:]:
                owners[0]["json_paths"].extend(owner["json_paths"])
                owner.update(status="skipped", details=f"Duplicate sidecar for {source.name}")
        else:
            for owner in owners:
                owner.update(status="error", details=f"Conflicting JSON sidecars for {source.name}")
    return tasks, matchers


def _confirmed_companion(task, matcher, claimed_sources, exiftool_path):
    source = task["source"]
    if source.suffix.casefold() not in IMAGE_EXTENSIONS:
        return None
    candidates = [source.parent / name for name in matcher.by_stem.get(normalized_name(source.stem), ()) if Path(name).suffix.casefold() in {".mov", ".mp4"}]
    candidates = [candidate for candidate in candidates if candidate not in claimed_sources]
    if not candidates:
        return None
    if len(candidates) > 1:
        task["details"] = "Multiple companion videos; automatic pairing skipped"
        return None
    try:
        image_identifier = get_content_identifier(str(source), exiftool_path)
        if not image_identifier:
            return None
        video_identifier = get_content_identifier(str(candidates[0]), exiftool_path)
        if image_identifier == video_identifier:
            task["identifier"] = image_identifier
            return candidates[0]
        task["details"] = "Live Photo identifiers are missing or different; video left untouched"
    except (OSError, ValueError, RuntimeError) as error:
        task["details"] = f"Live Photo check skipped: {error}"
    return None


def _safe_parent(destination, root):
    if not destination.is_relative_to(root) or not destination.resolve().is_relative_to(root):
        raise ValueError("Output path is outside the selected folder")
    parent = destination.parent
    while parent != root:
        if parent.is_symlink():
            raise ValueError(f"Output folder is a symbolic link: {parent}")
        parent = parent.parent
    if destination.is_symlink():
        raise ValueError(f"Output file is a symbolic link: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)


def _move_no_replace(source, destination):
    if os.name == "nt":
        source.rename(destination)
    else:
        os.link(source, destination)
        try:
            source.unlink()
        except OSError:
            destination.unlink()
            raise


def _write_metadata(path, metadata, exiftool_path, preserve_identifier=False):
    if path.suffix.casefold() == ".mkv":
        raise ValueError("MKV metadata cannot be written by ExifTool; original and JSON left untouched")
    arguments = (str(path), metadata["latitude"], metadata["longitude"], metadata["altitude"], metadata["timestamp"], metadata["description"])
    if path.suffix.casefold() in {".jpg", ".jpeg"} and not preserve_identifier:
        try:
            set_photo_metadata(*arguments)
        except Exception as error:
            try:
                set_image_metadata(*arguments, exiftool_path=exiftool_path)
            except Exception as fallback_error:
                raise RuntimeError(f"JPEG metadata failed ({error}); ExifTool fallback failed ({fallback_error})") from fallback_error
    elif path.suffix.casefold() in VIDEO_EXTENSIONS:
        set_video_metadata(*arguments, exiftool_path=exiftool_path)
    else:
        set_image_metadata(*arguments, exiftool_path=exiftool_path)
    return setWindowsTime(str(path), metadata["timestamp"])


def _restore(task, root, exiftool_path):
    relative_folder = task["source"].parent.relative_to(root)
    output = root / task.get("output_folder", "MatchedMedia") / relative_folder
    items = [(task["source"], output / task["source"].name)]
    if task["companion"] is not None:
        items.append((task["companion"], output / task["companion"].name))
    if task["raw"] is not None:
        items.append((task["raw"], root / "EditedRaw" / relative_folder / task["raw"].name))
    for source, destination in items:
        _safe_parent(destination, root)
        if destination.exists():
            raise FileExistsError(f"Output already exists; nothing overwritten: {destination.relative_to(root)}")
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"Original media is missing or unsafe: {source.name}")
        if source.stat().st_dev != destination.parent.stat().st_dev:
            raise OSError("Output folders must be on the same filesystem; media will not be copied")
    sidecars = [(path, path.read_bytes(), path.stat()) for path in task.get("json_paths", [task["json_path"]])]
    moved = []
    deleted = []
    warnings = []
    try:
        for source, destination in items:
            identifier = task.get("identifier") if source in (task["source"], task["companion"]) else None
            warning = _write_metadata(source, task["metadata"], exiftool_path, preserve_identifier=bool(identifier))
            if identifier and get_content_identifier(str(source), exiftool_path) != identifier:
                raise RuntimeError("Live Photo identifier changed during metadata writing; media left in original folder")
            if warning:
                warnings.append(warning)
        for source, destination in items:
            _move_no_replace(source, destination)
            moved.append((source, destination))
        for sidecar in sidecars:
            sidecar[0].unlink()
            deleted.append(sidecar)
        return True, warnings
    except Exception as error:
        rollback_errors = []
        for source, destination in reversed(moved):
            try:
                _move_no_replace(destination, source)
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))
        for path, content, original_stat in deleted:
            try:
                with path.open("xb") as stream:
                    stream.write(content)
                os.utime(path, (original_stat.st_atime, original_stat.st_mtime))
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))
        if rollback_errors:
            raise RuntimeError(f"{error}; could not restore every original location: {'; '.join(rollback_errors)}") from error
        raise


def _report(root, records):
    folder = root / "MatchedMedia"
    _safe_parent(folder / "matching-report.csv", root)
    descriptor, filename = tempfile.mkstemp(prefix="matching-report-", suffix=".csv", dir=folder)
    with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("json", "media", "details"))
        writer.writeheader()
        for record in records:
            if record.get("status") != "error":
                continue
            values = {key: str(record.get(key, "")) for key in writer.fieldnames}
            values = {key: "'" + value if value.startswith(("=", "+", "-", "@")) else value for key, value in values.items()}
            writer.writerow(values)
    return filename


def mainProcess(browserPath, window, editedW, exiftoolPath=None, dry_run=False, cancel_event=None):
    try:
        root = Path(browserPath).expanduser().resolve(strict=True)
        if not root.is_dir() or root.name in {"MatchedMedia", "EditedRaw"}:
            raise ValueError("Select the original Takeout folder, not an output folder")
        tasks, matchers = _plan(root, editedW.strip(), window, cancel_event)
        if not tasks and not (cancel_event is not None and cancel_event.is_set()):
            raise ValueError("No JSON files found in the selected folder")
        claimed_sources = {task["source"] for task in tasks if task["source"] is not None}
        for task in tasks:
            folder = task["json_path"].parent
            name = normalized_name(sidecar_media_name(task["json_path"].name)[0])
            claimed_sources.update(folder / filename for filename in matchers[folder].by_normalized_name.get(name, ()))
        total = len(tasks)
        covered = {path for task in tasks for path in (task["source"], task["raw"]) if path is not None}
        counts = Counter(task["status"] for task in tasks if task["status"] != "pending")
        counts["unmatched"] = sum(folder / name not in covered for folder, matcher in matchers.items() for name in matcher.names)
        window.write_event_value("-UPDATE_COUNTS-", dict(counts))
        with exiftool_batch():
            for index, task in enumerate(tasks):
                if cancel_event is not None and cancel_event.is_set():
                    if task["status"] == "pending":
                        task.update(status="cancelled", details="Cancelled before writing")
                    continue
                if task["status"] == "pending":
                    try:
                        task["companion"] = _confirmed_companion(task, matchers[task["source"].parent], claimed_sources, exiftoolPath)
                        if task["companion"] is not None:
                            claimed_sources.add(task["companion"])
                            if task["companion"] not in covered:
                                covered.add(task["companion"])
                                counts["unmatched"] -= 1
                        if dry_run:
                            task["status"] = "preview"
                        else:
                            created, warnings = _restore(task, root, exiftoolPath)
                            task["status"] = "restored" if created else "already_restored"
                            task["details"] = "; ".join(filter(None, (task["details"], *warnings)))
                    except Exception as error:
                        task.update(status="error", details=str(error))
                    counts[task["status"]] += 1
                window.write_event_value("-UPDATE_COUNTS-", dict(counts))
                log(window, f"{task['status'].upper()}: {task['media'] or task['json']}" + (f" | {task['details']}" if task["details"] else ""))
                window.write_event_value("-UPDATE_PROGRESS-", (round((index + 1) * 100 / total, 1), task["media"] or task["json"]))
        records = list(tasks)
        for folder, matcher in matchers.items():
            for name in sorted(matcher.names):
                if folder / name not in covered:
                    records.append({"json": "", "media": str((folder / name).relative_to(root)), "status": "unmatched", "rule": "", "details": "No confirmed metadata match; original left untouched"})
        report_path = _report(root, records)
        summary = dict(Counter(record["status"] for record in records))
        summary.update(report=report_path, dry_run=dry_run, cancelled=cancel_event is not None and cancel_event.is_set())
        log(window, f"Report: {report_path}")
        window.write_event_value("-UPDATE_SUMMARY-", summary)
        window.write_event_value("-UPDATE_DONE-", (summary.get("restored", 0), summary.get("error", 0)))
        return summary
    except Exception as error:
        log(window, f"ERROR: {error}")
        window.write_event_value("-UPDATE_ERROR-", str(error))
        return {"error": 1, "details": str(error)}