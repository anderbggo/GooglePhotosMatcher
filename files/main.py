import concurrent.futures
import csv
import itertools
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from exiftool_runner import exiftool_batch, run_exiftool
from journal import CrashProofReportJournal
from matching import (
    IMAGE_EXTENSIONS,
    AmbiguousMatchError,
    MediaMatcher,
    VIDEO_EXTENSIONS,
    detect_media_extension,
    normalized_name,
    same_media_type,
    sidecar_media_name,
)
from metadata import (
    get_container_datetime,
    get_content_identifier,
    parse_filename_timestamp,
    set_content_identifier,
    set_image_metadata,
    set_photo_metadata,
    set_video_metadata,
    setWindowsTime,
)

FORCED_FOLDER = "ForcedMatches"

# Riskier recoveries tried in order on a temporary copy during force match.
FORCE_STEPS = (
    ("ignored minor metadata errors", ()),
    ("rebuilt damaged metadata", ("-ThumbnailImage=", "-all=", "-tagsfromfile", "@", "-all:all", "-unsafe", "-icc_profile")),
    ("removed existing embedded metadata", ("-all=",)),
)


def log(window, msg):
    window.write_event_value("-LOG-", msg)
    print(msg)


def _metadata(data, lenient=False, synthesized_timestamp=None):
    timestamp = synthesized_timestamp
    if timestamp is None:
        for key in ("photoTakenTime", "creationTime", "photoLastModifiedTime"):
            value = data.get(key)
            if isinstance(value, dict) and value.get("timestamp") is not None:
                raw_timestamp = value["timestamp"]
                if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (str, int)):
                    raise ValueError("Invalid photo timestamp")
                cand = int(raw_timestamp)
                if cand > 0:
                    try:
                        datetime.fromtimestamp(cand)
                        timestamp = cand
                        break
                    except (ValueError, OverflowError):
                        pass
    if timestamp is None:
        raise ValueError("Missing photo timestamp")
    coordinates = (0.0, 0.0, 0.0)
    try:
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
    except (ValueError, TypeError, OverflowError):
        if not lenient:
            raise
        coordinates = (0.0, 0.0, 0.0)
    description = data.get("description") or ""
    if not isinstance(description, str):
        if not lenient:
            raise ValueError("Invalid description")
        description = ""
    return {"timestamp": timestamp, "latitude": coordinates[0], "longitude": coordinates[1], "altitude": coordinates[2], "description": description}


def _scan_error(error):
    raise error


def _plan(root, edited_word, window, cancel_event, force=False, self_heal=False):
    tasks = []
    matchers = {}
    scan_count = 0
    last_scan_update = 0.0
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
            scan_count += 1
            now = time.monotonic()
            if scan_count % 50 == 0 or (now - last_scan_update) >= 0.1:
                last_scan_update = now
                window.write_event_value("-UPDATE_PROGRESS-", (0, f"Scanning: {json_path.name}"))
            try:
                data = None
                try:
                    with json_path.open(encoding="utf-8-sig") as stream:
                        data = json.load(stream)
                except (OSError, UnicodeDecodeError, ValueError) as json_err:
                    if self_heal:
                        media_name, _ = sidecar_media_name(json_name)
                        cand = None
                        if media_name and media_name in matcher.names:
                            cand = media_name
                        elif media_name:
                            cand_stem = normalized_name(os.path.splitext(media_name)[0])
                            stem_matches = matcher.by_stem.get(cand_stem, [])
                            if len(stem_matches) == 1:
                                cand = stem_matches[0]
                        if cand and (folder / cand).is_file():
                            synthesized = parse_filename_timestamp(cand) or parse_filename_timestamp(json_name) or get_container_datetime(str(folder / cand))
                            if synthesized:
                                data = {
                                    "title": cand,
                                    "photoTakenTime": {"timestamp": str(synthesized)},
                                    "description": "",
                                    "geoData": {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0},
                                }
                                task["details"] = "Self-healed: recovered metadata from filename/container (corrupted JSON sidecar)"
                    if data is None:
                        raise json_err
                if not isinstance(data, dict):
                    raise ValueError("JSON metadata must be an object")
                title = data.get("title")
                if not title or not any(key in data for key in ("photoTakenTime", "creationTime", "photoLastModifiedTime")):
                    task.update(status="skipped", details="Not a photo/video metadata sidecar")
                    continue
                if not isinstance(title, str):
                    raise ValueError("Invalid JSON title")
                task["title"] = title
                try:
                    task["metadata"] = _metadata(data)
                except (ValueError, TypeError, OverflowError) as error:
                    synthesized = parse_filename_timestamp(title) or parse_filename_timestamp(json_name) if self_heal else None
                    if synthesized is None and self_heal:
                        try:
                            cand_edited, cand_original = matcher.match(title, json_name, edited_word)
                            cand_file = cand_edited or cand_original
                            if cand_file and (folder / cand_file).is_file():
                                synthesized = get_container_datetime(str(folder / cand_file))
                                if synthesized is not None:
                                    task["details"] = "Self-healed: recovered timestamp from media header"
                        except Exception:
                            pass
                    if synthesized is not None:
                        try:
                            task["metadata"] = _metadata(data, lenient=True, synthesized_timestamp=synthesized)
                            if not task["details"]:
                                task["details"] = "Self-healed: restored timestamp from filename"
                        except Exception:
                            if not force:
                                raise
                            task["metadata"] = _metadata(data, lenient=True)
                            task["details"] = f"Force match: discarded invalid metadata ({error})"
                    elif self_heal:
                        try:
                            task["metadata"] = _metadata(data, lenient=True)
                            task["details"] = f"Self-healed: discarded invalid metadata ({error})"
                        except Exception:
                            if not force:
                                raise
                            task["metadata"] = _metadata(data, lenient=True)
                            task["details"] = f"Force match: discarded invalid metadata ({error})"
                    elif not force:
                        raise
                    else:
                        task["metadata"] = _metadata(data, lenient=True)
                        task["details"] = f"Force match: discarded invalid metadata ({error})"
                edited, original = matcher.match(title, json_name, edited_word)
                original_with_separate_edit = False
                if edited and sidecar_owners.get(normalized_name(edited), set()) - {json_name}:
                    original_with_separate_edit = original is not None
                    edited = None
                selected = edited or original
                if not selected:
                    task.update(status="error", details=f"No unambiguous media match for {title}", match_failed=True)
                    continue
                task.update(source=folder / selected, media=str((folder / selected).relative_to(root)), rule=matcher.last_rule)
                if original_with_separate_edit:
                    task["output_folder"] = "EditedRaw"
                if edited and original and edited != original:
                    task["raw"] = folder / original
            except (OSError, ValueError, TypeError, OverflowError) as error:
                task.update(status="error", details=str(error), match_failed=isinstance(error, AmbiguousMatchError))

    _resolve_cross_folder_matches(tasks, matchers, root)
    if force:
        _force_sources(tasks, matchers, root)
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


def _resolve_cross_folder_matches(tasks, matchers, root):
    """Resolves multi-part Takeout archive splits and album-vs-year partitions across folders."""
    claimed = {path for task in tasks for path in (task["source"], task["raw"]) if path is not None}
    unclaimed = {}
    for folder, matcher in matchers.items():
        for name in sorted(matcher.names):
            media_path = folder / name
            if media_path not in claimed:
                unclaimed[media_path] = folder
    for task in tasks:
        if not task.get("match_failed"):
            continue
        json_path = task["json_path"]
        title = task.get("title", "")
        names = {sidecar_media_name(json_path.name)[0], title}
        stems = {normalized_name(os.path.splitext(n)[0]) for n in names if n}

        # Strategy A: Subpath Sibling Match (Multi-Part Archive Splits)
        folder_name = json_path.parent.name.casefold()
        subpath_candidates = [
            media_path for media_path in unclaimed
            if media_path not in claimed
            and media_path.parent != json_path.parent
            and media_path.parent.name.casefold() == folder_name
            and (media_path.name in names or normalized_name(media_path.stem) in stems)
        ]
        if len(subpath_candidates) == 1:
            source = subpath_candidates[0]
            claimed.add(source)
            task.update(
                status="pending", source=source, media=str(source.relative_to(root)),
                rule="cross-part subpath match", match_failed=False,
                details="; ".join(filter(None, (task["details"], f"Resolved across parts from {source.parent.name}"))),
            )
            continue

        # Strategy B: Global Unique Stem Match (Album vs Year Folders)
        title_ext = os.path.splitext(title)[1].casefold()
        stem_candidates = [
            media_path for media_path in unclaimed
            if media_path not in claimed
            and media_path.parent != json_path.parent
            and normalized_name(media_path.stem) in stems
            and (
                media_path.suffix.casefold() == title_ext
                or (title_ext in IMAGE_EXTENSIONS and media_path.suffix.casefold() in IMAGE_EXTENSIONS)
                or (title_ext in VIDEO_EXTENSIONS and media_path.suffix.casefold() in VIDEO_EXTENSIONS)
            )
        ]
        if len(stem_candidates) == 1:
            source = stem_candidates[0]
            claimed.add(source)
            task.update(
                status="pending", source=source, media=str(source.relative_to(root)),
                rule="cross-folder stem match", match_failed=False,
                details="; ".join(filter(None, (task["details"], f"Resolved from {source.parent.name}"))),
            )


def _force_sources(tasks, matchers, root):
    """Pair failed sidecars with the only unclaimed file sharing their name but not their extension."""
    claimed = {path for task in tasks for path in (task["source"], task["raw"]) if path is not None}
    for task in tasks:
        if not task.get("match_failed"):
            continue
        folder = task["json_path"].parent
        matcher = matchers[folder]
        names = (sidecar_media_name(task["json_path"].name)[0], task["title"])
        stems = {normalized_name(os.path.splitext(name)[0]) for name in names}
        candidates = {folder / name for stem in stems for name in matcher.by_stem.get(stem, ()) if folder / name not in claimed}
        title_extension = os.path.splitext(task["title"])[1].casefold()
        for family in (IMAGE_EXTENSIONS, VIDEO_EXTENSIONS):
            if title_extension in family:
                candidates = {path for path in candidates if path.suffix.casefold() in family}
        if len(candidates) != 1:
            continue
        source = candidates.pop()
        claimed.add(source)
        task.update(
            status="pending", source=source, media=str(source.relative_to(root)), rule="force: same name", match_failed=False,
            details="; ".join(filter(None, (task["details"] if task["details"].startswith("Force match") else "", f"Force match: used {source.name} for {task['title']}"))),
        )


def _free_names(destinations):
    """Add the same (n) suffix to every destination so grouped files keep matching names."""
    for number in itertools.count():
        candidates = [path if number == 0 else path.with_name(f"{path.stem}({number}){path.suffix}") for path in destinations]
        if not any(path.exists() for path in candidates):
            return candidates


def _fix_extensions(task, self_heal=False):
    """Rename media whose content belongs to another format; returns the renames for rollback."""
    renamed = []
    try:
        for key in ("source", "raw"):
            path = task[key]
            if path is None:
                continue
            actual = detect_media_extension(path)
            if not actual or same_media_type(actual, path.suffix):
                continue
            target = _free_names([path.with_suffix(actual)])[0]
            _move_no_replace(path, target)
            renamed.append((key, target, path))
            task[key] = target
            prefix = "Self-healed" if self_heal else "Force match"
            task["details"] = "; ".join(filter(None, (task["details"], f"{prefix}: renamed {path.name} to {target.name} (real file type)")))
    except OSError:
        _undo_renames(task, renamed)
        raise
    return renamed


def _undo_renames(task, renamed):
    for key, current, original in reversed(renamed):
        _move_no_replace(current, original)
        task[key] = original


def _give_up(task):
    details = task["details"] if task["details"].startswith("Force match failed") else f"Force match failed: {task['details']}"
    task.update(status="unmatched", details=details, force_failed=True)


def _confirmed_companion(task, matcher, claimed_sources, exiftool_path, self_heal=False):
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
    companion = candidates[0]
    try:
        image_identifier = get_content_identifier(str(source), exiftool_path)
        video_identifier = get_content_identifier(str(companion), exiftool_path)
        if image_identifier and image_identifier == video_identifier:
            task["identifier"] = image_identifier
            return companion
        if self_heal:
            if not image_identifier and not video_identifier:
                new_id = str(uuid.uuid4()).upper()
                try:
                    set_content_identifier(str(companion), new_id, exiftool_path)
                    try:
                        set_content_identifier(str(source), new_id, exiftool_path)
                    except Exception:
                        pass
                    task["identifier"] = new_id
                    task["identifier_synthetic"] = True
                    task["details"] = "; ".join(filter(None, (task["details"], "Self-healed: generated Live Photo identifier")))
                    return companion
                except Exception:
                    pass
            elif image_identifier and not video_identifier:
                try:
                    set_content_identifier(str(companion), image_identifier, exiftool_path)
                    task["identifier"] = image_identifier
                    task["details"] = "; ".join(filter(None, (task["details"], "Self-healed: synchronized Live Photo identifier to video")))
                    return companion
                except Exception:
                    pass
            elif not image_identifier and video_identifier:
                try:
                    set_content_identifier(str(source), video_identifier, exiftool_path)
                    task["identifier"] = video_identifier
                    task["details"] = "; ".join(filter(None, (task["details"], "Self-healed: synchronized Live Photo identifier to image")))
                    return companion
                except Exception:
                    pass
        if not image_identifier:
            return None
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


def _write_metadata(path, metadata, exiftool_path, preserve_identifier=False, force=False, self_heal=False):
    try:
        return _write_metadata_once(path, metadata, exiftool_path, preserve_identifier)
    except Exception as error:
        if (not force and not self_heal) or path.suffix.casefold() == ".mkv":
            raise
        return _force_write(path, metadata, exiftool_path, preserve_identifier, error, self_heal=self_heal and not force)


def _force_write(path, metadata, exiftool_path, preserve_identifier, first_error, self_heal=False):
    errors = [str(first_error)]
    writer = set_video_metadata if path.suffix.casefold() in VIDEO_EXTENSIONS else set_image_metadata
    # Stripping metadata would destroy the Live Photo identifier.
    for label, cleanup in FORCE_STEPS[:1] if preserve_identifier else FORCE_STEPS:
        descriptor, name = tempfile.mkstemp(prefix=".gpm-force-", suffix=path.suffix, dir=path.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            shutil.copy2(path, temporary)
            if cleanup:
                run_exiftool(str(temporary), ["-overwrite_original", "-m", *cleanup], exiftool_path)
            writer(str(temporary), metadata["latitude"], metadata["longitude"], metadata["altitude"], metadata["timestamp"], metadata["description"], exiftool_path=exiftool_path, extra_options=("-m", "-api", "LargeFileSupport=1"))
            os.replace(temporary, path)
            warning = setWindowsTime(str(path), metadata["timestamp"])
            prefix = "Self-healed" if self_heal else "Force match"
            return "; ".join(filter(None, (f"{prefix}: {label}", warning)))
        except Exception as error:
            errors.append(f"{label}: {error}")
        finally:
            temporary.unlink(missing_ok=True)
    prefix = "Self-healing" if self_heal else "Force match"
    if any(
        any(frag.lower() in err.lower() for frag in ("truncated mdat atom", "format error in file", "file is empty", "no writable tags set", "corrupted", "not a valid png", "not a valid jpeg", "looks more like"))
        for err in errors
    ) or self_heal:
        warning = setWindowsTime(str(path), metadata["timestamp"])
        res_prefix = "Self-healed" if self_heal else "Force match"
        return "; ".join(filter(None, (f"{res_prefix}: applied filesystem timestamp (metadata container write skipped)", warning)))
    raise RuntimeError(f"{prefix} failed: " + "; ".join(errors))


def _write_metadata_once(path, metadata, exiftool_path, preserve_identifier=False):
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


def _restore(task, root, exiftool_path, force=False, in_place=False, self_heal=False):
    if in_place:
        items = [(task["source"], task["source"])]
        if task["companion"] is not None:
            items.append((task["companion"], task["companion"]))
        if task["raw"] is not None:
            items.append((task["raw"], task["raw"]))
        for source, _ in items:
            if not source.is_file() or source.is_symlink():
                raise FileNotFoundError(f"Original media is missing or unsafe: {source.name}")
    else:
        subfolder = (FORCED_FOLDER,) if force else ()
        output = root.joinpath(task.get("output_folder", "MatchedMedia"), *subfolder)
        items = [(task["source"], output / task["source"].name)]
        if task["companion"] is not None:
            items.append((task["companion"], output / task["companion"].name))
        if task["raw"] is not None:
            items.append((task["raw"], root.joinpath("EditedRaw", *subfolder, task["raw"].name)))
        items = list(zip([source for source, _ in items], _free_names([destination for _, destination in items])))
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
            warning = _write_metadata(source, task["metadata"], exiftool_path, preserve_identifier=bool(identifier), force=force, self_heal=self_heal)
            if identifier and get_content_identifier(str(source), exiftool_path) != identifier:
                if self_heal or force or task.get("identifier_synthetic"):
                    warning = "; ".join(filter(None, (warning, "Self-healed: restored metadata; Live Photo identifier not preserved by container")))
                else:
                    raise RuntimeError("Live Photo identifier changed during metadata writing; media left in original folder")
            if warning:
                warnings.append(warning)
        if not in_place:
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


def _report(root, records, in_place=False):
    folder = root if in_place else root / "MatchedMedia"
    _safe_parent(folder / "matching-report.csv", root)
    descriptor, filename = tempfile.mkstemp(prefix="matching-report-", suffix=".csv", dir=folder)
    with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("json", "media", "details"))
        writer.writeheader()
        for record in records:
            if record.get("status") != "error" and not record.get("force_failed"):
                continue
            values = {key: str(record.get(key, "")) for key in writer.fieldnames}
            values = {key: "'" + value if value.startswith(("=", "+", "-", "@")) else value for key, value in values.items()}
            writer.writerow(values)
    return filename


def mainProcess(browserPath, window, editedW, exiftoolPath=None, dry_run=False, cancel_event=None, force=False, in_place=False, self_heal=False, merge_takeouts=False, concurrency=None):
    try:
        root = Path(browserPath).expanduser().resolve(strict=True)
        if not root.is_dir() or root.name in {"MatchedMedia", "EditedRaw"}:
            raise ValueError("Select the original Takeout folder, not an output folder")
        if merge_takeouts:
            from consolidator import consolidate_takeout_partitions
            root = consolidate_takeout_partitions(root, window, cancel_event)
        tasks, matchers = _plan(root, editedW.strip(), window, cancel_event, force, self_heal)
        if force:
            for task in tasks:
                if task["status"] == "error":
                    _give_up(task)
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

        # Determine worker concurrency from user preferences / slot
        if concurrency is None or concurrency == 1 or concurrency == "1":
            max_workers = 1
        elif isinstance(concurrency, str):
            if concurrency.lower().startswith("auto"):
                max_workers = os.cpu_count() or 4
            else:
                match = re.search(r"\d+", concurrency)
                max_workers = int(match.group(0)) if match else (os.cpu_count() or 4)
        else:
            max_workers = max(1, int(concurrency))

        # Real-time anti-corruption report journal (immediately synced to disk)
        journal_dir = root if in_place else root / "MatchedMedia"
        journal_dir.mkdir(parents=True, exist_ok=True)
        journal_path = journal_dir / "matching-journal.csv"
        journal = CrashProofReportJournal(journal_path)

        from governor import AdaptiveGovernor
        governor = AdaptiveGovernor()

        count_lock = threading.Lock()
        companion_lock = threading.Lock()
        progress_lock = threading.Lock()
        completed_count = 0
        last_progress_update = 0.0

        def _process_single_task(task, index=0):
            nonlocal completed_count, last_progress_update
            governor.govern()
            if cancel_event is not None and cancel_event.is_set():
                if task["status"] == "pending":
                    task.update(status="cancelled", details="Cancelled before writing")
                return task
            if task["status"] == "pending":
                renamed = []
                try:
                    if (force or self_heal) and not dry_run:
                        renamed = _fix_extensions(task, self_heal=self_heal and not force)
                    with companion_lock:
                        task["companion"] = _confirmed_companion(task, matchers[task["source"].parent], claimed_sources, exiftoolPath, self_heal)
                        if task["companion"] is not None:
                            claimed_sources.add(task["companion"])
                            if task["companion"] not in covered:
                                covered.add(task["companion"])
                                with count_lock:
                                    counts["unmatched"] -= 1
                    if dry_run:
                        task["status"] = "preview"
                    else:
                        created, warnings = _restore(task, root, exiftoolPath, force, in_place, self_heal)
                        task["status"] = "restored" if created else "already_restored"
                        task["details"] = "; ".join(filter(None, (task["details"], *warnings)))
                except Exception as error:
                    task.update(status="error", details=str(error))
                    try:
                        _undo_renames(task, renamed)
                    except OSError as rename_error:
                        task["details"] += f"; could not restore original file name: {rename_error}"
                    if force:
                        _give_up(task)
                with count_lock:
                    counts[task["status"]] += 1

                # Crash-safe incremental journal write
                journal.record(
                    task.get("json", ""),
                    task.get("media", ""),
                    task.get("status", ""),
                    task.get("rule", ""),
                    task.get("details", ""),
                )

            with progress_lock:
                completed_count += 1
                now = time.monotonic()
                if max_workers == 1 or (now - last_progress_update) >= 0.05 or completed_count == total:
                    last_progress_update = now
                    window.write_event_value("-UPDATE_COUNTS-", dict(counts))
                    window.write_event_value("-UPDATE_PROGRESS-", (round(completed_count * 100 / total, 1), task["media"] or task["json"]))
            log(window, f"{task['status'].upper()}: {task['media'] or task['json']}" + (f" | {task['details']}" if task["details"] else ""))
            return task

        if max_workers > 1:
            def _thread_worker(t):
                with exiftool_batch():
                    return _process_single_task(t)

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(_thread_worker, tasks))
        else:
            with exiftool_batch():
                for index, task in enumerate(tasks):
                    _process_single_task(task, index=index)

        records = list(tasks)
        for folder, matcher in matchers.items():
            for name in sorted(matcher.names):
                if folder / name not in covered:
                    unmatched_rec = {"json": "", "media": str((folder / name).relative_to(root)), "status": "unmatched", "rule": "", "details": "No confirmed metadata match; original left untouched"}
                    records.append(unmatched_rec)
                    journal.record("", unmatched_rec["media"], "unmatched", "", unmatched_rec["details"])

        report_path = _report(root, records, in_place=in_place)
        summary = dict(Counter(record["status"] for record in records))
        summary.update(report=report_path, journal=str(journal_path), dry_run=dry_run, cancelled=cancel_event is not None and cancel_event.is_set())
        log(window, f"Report: {report_path}")
        window.write_event_value("-UPDATE_SUMMARY-", summary)
        window.write_event_value("-UPDATE_DONE-", (summary.get("restored", 0), summary.get("error", 0)))
        return summary
    except Exception as error:
        log(window, f"ERROR: {error}")
        window.write_event_value("-UPDATE_ERROR-", str(error))
        return {"error": 1, "details": str(error)}