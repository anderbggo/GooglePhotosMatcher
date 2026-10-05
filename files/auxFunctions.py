import os
import sys
import json
import piexif
import subprocess
import platform
import shutil
import re
import unicodedata
import queue
import signal
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from fractions import Fraction

if platform.system() == "Windows":
    from win32_setctime import setctime
else:
    setctime = None

def resource_path(relative_path: str) -> str:
    """ Finds the actual path to the resource file for PyInstaller (_MEIPASS) """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

def get_exiftool_path(exiftool_path=None) -> str | None:
    """ Retrieves the path for the ExifTool binary """
    if exiftool_path:
        exiftool_path = os.path.abspath(os.path.expanduser(exiftool_path.strip().strip('"')))
        if os.path.isfile(exiftool_path) and os.access(exiftool_path, os.X_OK):
            return exiftool_path
        raise FileNotFoundError(f"ExifTool not found at {exiftool_path}")

    base_paths = [resource_path("vendor/exiftool"), resource_path("")]
    if getattr(sys, "frozen", False):
        base_paths.append(os.path.dirname(sys.executable))

    exiftool_names = ["exiftool.exe", "exiftool"] if platform.system() == "Windows" else ["exiftool"]
    for base_path in base_paths:
        for exiftool_name in exiftool_names:
            candidate = os.path.normpath(os.path.join(base_path, exiftool_name))
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

    candidate = shutil.which("exiftool")
    if candidate:
        return candidate

    return None






# MEDIA SEARCH & UTILS
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".heif", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".3gp", ".m4v", ".mkv"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
EDITED_SUFFIXES = ("editado", "editada", "edited", "modifié", "modifiée", "bearbeitet", "bewerkt", "modificato", "modificata", "redigerad")
HIDDEN_SUFFIXES = ("_PORTRAIT", "PORTRAIT", "_NFNR", "_MFNR")


def normalized_name(name):
    return unicodedata.normalize("NFC", name).casefold()


def sidecar_media_name(json_name):
    name = json_name[:-5] if json_name.casefold().endswith(".json") else json_name
    duplicate = ""
    trailing_number = re.search(r"\((\d+)\)$", name)
    if trailing_number:
        duplicate = trailing_number.group(1)
        name = name[:trailing_number.start()]
    name = re.sub(r"\.supplemental(?:-[a-z]*)?$", "", name, flags=re.IGNORECASE)
    extension_number = re.search(r"\((\d+)\)$", name)
    if extension_number:
        duplicate = extension_number.group(1)
        name = name[:extension_number.start()]
    stem, extension = os.path.splitext(name)
    stem_number = re.search(r"\((\d+)\)$", stem)
    if not duplicate and stem_number:
        duplicate = stem_number.group(1)
    if duplicate and extension.casefold() in MEDIA_EXTENSIONS and not stem.endswith(f"({duplicate})"):
        name = f"{stem}({duplicate}){extension}"
    return name, duplicate


class AmbiguousMatchError(ValueError):
    def __init__(self, candidates):
        self.candidates = sorted(candidates)
        super().__init__("Ambiguous match: " + ", ".join(self.candidates))


class MediaMatcher:
    def __init__(self, path, filenames=None, excluded=()):
        if filenames is None:
            with os.scandir(path) as entries:
                filenames = [entry.name for entry in entries if entry.is_file(follow_symlinks=False)]
        self.names = {
            name for name in filenames
            if os.path.splitext(name)[1].casefold() in MEDIA_EXTENSIONS and name not in excluded
        }
        self.by_normalized_name = {}
        self.by_stem = {}
        for name in sorted(self.names):
            self.by_normalized_name.setdefault(normalized_name(name), []).append(name)
            self.by_stem.setdefault(normalized_name(os.path.splitext(name)[0]), []).append(name)
        self.last_rule = ""

    def _lookup(self, candidates):
        exact = self.names.intersection(candidates)
        if len(exact) > 1:
            raise AmbiguousMatchError(exact)
        if exact:
            return next(iter(exact))
        matches = {
            name for candidate in candidates
            for name in self.by_normalized_name.get(normalized_name(candidate), ())
        }
        if len(matches) > 1:
            raise AmbiguousMatchError(matches)
        return next(iter(matches), None)

    @staticmethod
    def _variants(name):
        replaced = re.sub(r'[<>:"/\\|?*]', "_", name)
        return list(dict.fromkeys((name, fixTitle(name), replaced)))

    def _edited(self, names, edited_word):
        def candidates(source_names, suffixes):
            results = []
            for name in source_names:
                stem, extension = os.path.splitext(name)
                for suffix in suffixes:
                    results.append(f"{stem}-{suffix}{extension}")
                    duplicate = re.search(r"\((\d+)\)$", stem)
                    if duplicate:
                        results.append(f"{stem[:duplicate.start()]}-{suffix}{duplicate.group()}{extension}")
            return results

        if edited_word:
            found = self._lookup(candidates(names, (edited_word.strip().lstrip("-"),)))
            if found:
                return found
        found = self._lookup(candidates(names, EDITED_SUFFIXES))
        if found:
            return found
        truncated = []
        for name in names:
            stem, extension = os.path.splitext(name)
            duplicate = re.search(r"\((\d+)\)$", stem)
            counter = duplicate.group() if duplicate else ""
            base = stem[:duplicate.start()] if duplicate else stem
            for limit in (47, 51 - len(extension)):
                if len(base) > limit:
                    truncated.append(f"{base[:limit]}{counter}{extension}")
        suffixes = (edited_word.strip().lstrip("-"), *EDITED_SUFFIXES) if edited_word else EDITED_SUFFIXES
        return self._lookup(candidates(truncated, suffixes))

    def match(self, title, json_name=None, edited_word=""):
        self.last_rule = ""
        sidecar, duplicate = sidecar_media_name(json_name) if json_name else ("", "")
        title_stem, title_extension = os.path.splitext(title)
        title_number = re.search(r"\((\d+)\)$", title_stem)
        if not duplicate and title_number:
            duplicate = title_number.group(1)
        if duplicate and not title_stem.endswith(f"({duplicate})"):
            title = f"{title_stem}({duplicate}){title_extension}"
        primary_names = list(dict.fromkeys(name for name in (sidecar, title) if name))
        original = None
        for name in primary_names:
            original = self._lookup((name,))
            if original:
                self.last_rule = "sidecar name" if name == sidecar else "JSON title"
                break
        if original is None:
            variants = [variant for name in primary_names for variant in self._variants(name)[1:]]
            original = self._lookup(variants)
            if original:
                self.last_rule = "sanitized name"
        if original is None:
            hidden = []
            for name in primary_names:
                stem, extension = os.path.splitext(name)
                for suffix in HIDDEN_SUFFIXES:
                    hidden.append(f"{stem}{suffix}{extension}")
                    counter = re.search(r"\((\d+)\)$", stem)
                    if counter:
                        hidden.append(f"{stem[:counter.start()]}{suffix}{counter.group()}{extension}")
                    if stem.endswith(suffix):
                        hidden.append(f"{stem[:-len(suffix)]}{extension}")
            original = self._lookup(hidden)
            if original:
                self.last_rule = "camera suffix"
        if original is None:
            truncated_matches = set()
            for target in primary_names:
                target_stem, target_extension = os.path.splitext(normalized_name(target))
                for name in self.names:
                    stem, extension = os.path.splitext(normalized_name(name))
                    if duplicate and not stem.endswith(f"({duplicate})"):
                        continue
                    if target_extension in MEDIA_EXTENSIONS:
                        compare_stem = re.sub(r"\(\d+\)$", "", stem) if duplicate else stem
                        compare_target = re.sub(r"\(\d+\)$", "", target_stem) if duplicate else target_stem
                        shorter = min(len(compare_stem), len(compare_target))
                        if extension == target_extension and shorter in (46, 47, 50, 51):
                            if compare_stem.startswith(compare_target) or compare_target.startswith(compare_stem):
                                truncated_matches.add(name)
                    elif len(target) in (46, 47, 50, 51) and normalized_name(name).startswith(normalized_name(target)):
                        truncated_matches.add(name)
            if len(truncated_matches) > 1:
                raise AmbiguousMatchError(truncated_matches)
            original = next(iter(truncated_matches), None)
            if original:
                self.last_rule = "unique truncated name"
        edited_sources = [original] if original else [variant for name in primary_names for variant in self._variants(name)]
        edited = self._edited(edited_sources, edited_word)
        if edited and not self.last_rule:
            self.last_rule = "edited version"
        return edited, original


def searchMedia(path, title, mediaMoved, nonEdited, editedWord, json_name=None):
    """Return an edited/original pair without guessing between ambiguous files."""
    matcher = MediaMatcher(path, excluded=mediaMoved)
    try:
        return matcher.match(title, json_name, editedWord)
    except AmbiguousMatchError:
        return None, None

def fixTitle(title):
    """Removes incompatible characters from the filename"""
    bad_chars = '%<>=:?¿*#&{}\\|@!+|"\''
    return str(title).translate(str.maketrans('', '', bad_chars))

def checkIfSameName(title: str, titleFixed, mediaMoved, recursionTime):
    """Recursive function to find a unique name if repeated."""
    if titleFixed in mediaMoved:
        titleFixed = title.rsplit('.', 1)[0] + "(" + str(recursionTime) + ")" + "." + title.rsplit('.', 1)[1]
        return checkIfSameName(title, titleFixed, mediaMoved, recursionTime + 1)
    else:
        return titleFixed

def setWindowsTime(filepath, timeStamp):
    """Sets file timestamps, including macOS creation time when available."""
    os.utime(filepath, (timeStamp, timeStamp))
    try:
        if setctime is not None:
            setctime(filepath, timeStamp)
        elif platform.system() == "Darwin":
            setfile = shutil.which("SetFile")
            if not setfile:
                return "Creation time unchanged: SetFile is not installed"
            creation_date = datetime.fromtimestamp(timeStamp).strftime("%m/%d/%Y %H:%M:%S")
            subprocess.run([setfile, "-d", creation_date, os.path.abspath(filepath)], check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        return f"Creation time unchanged: {error}"
    return None

# GPS & MATH CONVERSIONS
def to_deg(value, loc):
    """Converts decimal coordinates into (degrees, minutes, seconds, direction)"""
    if value < 0:
        loc_value = loc[0]
    elif value > 0:
        loc_value = loc[1]
    else:
        loc_value = loc[1]
    abs_value = abs(value)
    deg = int(abs_value)
    t1 = (abs_value - deg) * 60
    min = int(t1)
    sec = round((t1 - min) * 60, 5)
    return (deg, min, sec, loc_value)

def change_to_rational(number):
    """Converts a number to a rational (numerator, denominator) tuple"""
    f = Fraction(str(number))
    return (f.numerator, f.denominator)

# PHOTO METADATA (PIEXIF)
def set_photo_metadata(filepath, lat, lng, altitude, timeStamp, description=""):
    """Sets EXIF metadata for image files using the piexif library"""
    exif_dict = piexif.load(filepath)
    maker_note = exif_dict.get("Exif", {}).get(piexif.ExifIFD.MakerNote, b"")
    if isinstance(maker_note, bytes) and maker_note.startswith(b"Apple iOS"):
        raise ValueError("ExifTool is required to preserve Apple MakerNotes and Live Photo identifiers")

    date = datetime.fromtimestamp(timeStamp).astimezone()
    dateTime = date.strftime("%Y:%m:%d %H:%M:%S")
    offset = date.strftime("%z")
    offset = offset[:3] + ":" + offset[3:]
    
    if '0th' not in exif_dict: exif_dict['0th'] = {}
    if 'Exif' not in exif_dict: exif_dict['Exif'] = {}

    exif_dict['0th'][piexif.ImageIFD.DateTime] = dateTime
    exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = dateTime
    exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = dateTime
    exif_dict['Exif'][piexif.ExifIFD.OffsetTime] = offset
    exif_dict['Exif'][piexif.ExifIFD.OffsetTimeOriginal] = offset
    exif_dict['Exif'][piexif.ExifIFD.OffsetTimeDigitized] = offset

    if description:
        exif_dict['0th'][piexif.ImageIFD.ImageDescription] = description.encode('utf-8')

    # GPS Injection
    if lat != 0.0 or lng != 0.0:
        lat_deg = to_deg(lat, ["S", "N"])
        lng_deg = to_deg(lng, ["W", "E"])

        exiv_lat = (change_to_rational(lat_deg[0]), change_to_rational(lat_deg[1]), change_to_rational(lat_deg[2]))
        exiv_lng = (change_to_rational(lng_deg[0]), change_to_rational(lng_deg[1]), change_to_rational(lng_deg[2]))

        exif_dict.setdefault('GPS', {}).update({
            piexif.GPSIFD.GPSVersionID: (2, 0, 0, 0),
            piexif.GPSIFD.GPSAltitudeRef: 1 if altitude < 0 else 0,
            piexif.GPSIFD.GPSAltitude: change_to_rational(round(abs(altitude), 2)),
            piexif.GPSIFD.GPSLatitudeRef: lat_deg[3],
            piexif.GPSIFD.GPSLatitude: exiv_lat,
            piexif.GPSIFD.GPSLongitudeRef: lng_deg[3],
            piexif.GPSIFD.GPSLongitude: exiv_lng,
        })

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, filepath)


_exiftool_state = threading.local()


class ExifToolSession:
    def __init__(self, timeout=60):
        self.timeout = timeout
        self.process = None
        self.executable = None
        self.output = None
        self.readers = []
        self.command_id = 0

    def _start(self, executable):
        if self.process is not None:
            if self.executable == executable and self.process.poll() is None:
                return
            self.close()
        self.executable = executable
        self.output = queue.Queue()
        self.process = subprocess.Popen(
            [executable, "-config", "", "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {"start_new_session": True}),
        )
        self.readers = []
        for name, stream in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
            reader = threading.Thread(target=self._read_output, args=(name, stream, self.output), daemon=True)
            self.readers.append(reader)
            reader.start()

    @staticmethod
    def _read_output(name, stream, output):
        try:
            for line in iter(stream.readline, b""):
                output.put((name, line))
        finally:
            output.put((name, None))

    def execute(self, executable, filepath, options):
        started = time.monotonic()
        try:
            self._start(executable)
            self.command_id += 1
            command = str(self.command_id)
            ready = f"{{ready{command}}}".encode("ascii")
            status_pattern = re.compile(rb"\{gpm_status_" + command.encode("ascii") + rb":(\d+)\}")
            arguments = ["-charset", "filename=UTF8", "-echo4", f"{{gpm_status_{command}:${{status}}}}", *options, os.path.abspath(filepath), f"-execute{command}"]
            self.process.stdin.write(("\n".join(arguments) + "\n").encode("utf-8"))
            self.process.stdin.flush()
            stdout, stderr = [], []
            stdout_done, returncode = False, None
            while not stdout_done or returncode is None:
                remaining = self.timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise queue.Empty
                name, line = self.output.get(timeout=remaining)
                if line is None:
                    if name == "stdout" and stdout_done or name == "stderr" and returncode is not None:
                        continue
                    raise RuntimeError("ExifTool ended before completing the current operation")
                if name == "stdout" and line.strip() == ready:
                    stdout_done = True
                elif name == "stderr" and (status := status_pattern.fullmatch(line.strip())):
                    returncode = int(status.group(1))
                else:
                    (stdout if name == "stdout" else stderr).append(line)
            return subprocess.CompletedProcess([executable, *options, filepath], returncode, b"".join(stdout), b"".join(stderr))
        except queue.Empty as error:
            self.close(force=True)
            raise RuntimeError(f"ExifTool timed out after {self.timeout:g} seconds: {os.path.basename(filepath)}") from error
        except Exception:
            self.close(force=True)
            raise

    def close(self, force=False):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None and not force:
                try:
                    process.stdin.write(b"-stay_open\nFalse\n")
                    process.stdin.flush()
                    process.wait(timeout=3)
                except (OSError, subprocess.SubprocessError):
                    force = True
            if process.poll() is None:
                if platform.system() == "Windows":
                    taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
                    try:
                        subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                    except (OSError, subprocess.SubprocessError):
                        pass
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        finally:
            for reader in self.readers:
                reader.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            self.readers = []


@contextmanager
def exiftool_batch():
    previous = getattr(_exiftool_state, "session", None)
    session = ExifToolSession()
    _exiftool_state.session = session
    try:
        yield session
    finally:
        _exiftool_state.session = previous
        session.close()


def _run_exiftool(filepath, options, exiftool_path=None):
    executable = get_exiftool_path(exiftool_path)
    if not executable:
        raise FileNotFoundError("ExifTool is required for this file. Use the standalone build, or install ExifTool on PATH when running the Python source.")
    args = [executable, "-config", "", "-charset", "filename=UTF8", *options, "--", os.path.abspath(filepath)]
    try:
        session = getattr(_exiftool_state, "session", None)
        if session is not None and not any(character in argument for argument in [*options, os.path.abspath(filepath)] for character in "\r\n\0"):
            result = session.execute(executable, filepath, options)
        else:
            result = subprocess.run(
                args,
                timeout=60,
                capture_output=True,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}),
            )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"ExifTool timed out after 60 seconds: {os.path.basename(filepath)}") from error
    if result.returncode != 0:
        details = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ExifTool failed: {details or 'unknown error'}")
    return result


def _write_exiftool_tags(filepath, tags, exiftool_path=None, extra_options=()):
    options = ["-overwrite_original", *extra_options]
    options.extend(f"-{key}={value}" for key, value in tags.items() if value != "")
    result = _run_exiftool(filepath, options, exiftool_path)
    warnings = result.stderr.decode("utf-8", errors="replace").strip()
    if re.search(r"error converting|isn't writable|not writable|not defined", warnings, flags=re.IGNORECASE):
        raise RuntimeError(f"ExifTool could not write requested metadata: {warnings}")


def set_image_metadata(filepath, lat, lng, altitude, timeStamp, description="", exiftool_path=None):
    date = datetime.fromtimestamp(timeStamp).astimezone()
    date_time = date.strftime("%Y:%m:%d %H:%M:%S")
    tags = {
        "EXIF:DateTimeOriginal": date_time,
        "EXIF:CreateDate": date_time,
        "EXIF:ModifyDate": date_time,
        "EXIF:OffsetTimeOriginal": date.strftime("%z")[:3] + ":" + date.strftime("%z")[3:],
        "XMP:DateCreated": date.isoformat(),
    }
    if description:
        tags["EXIF:ImageDescription"] = description
        tags["XMP:Description"] = description
    if lat != 0.0 or lng != 0.0:
        tags.update({
            "EXIF:GPSLatitude": abs(lat), "EXIF:GPSLatitudeRef": "S" if lat < 0 else "N",
            "EXIF:GPSLongitude": abs(lng), "EXIF:GPSLongitudeRef": "W" if lng < 0 else "E",
            "EXIF:GPSAltitude": abs(altitude), "EXIF:GPSAltitudeRef#": 1 if altitude < 0 else 0,
        })
    _write_exiftool_tags(filepath, tags, exiftool_path)


def set_video_metadata(filepath, lat, lng, altitude, timeStamp, description="", camera_make="", camera_model="", author="", software="", exiftool_path=None):
    """Injects metadata into video files using ExifTool"""
    date = datetime.fromtimestamp(timeStamp).astimezone()
    dateTime = date.strftime("%Y:%m:%d %H:%M:%S")

    # All the datas to transfer
    tags = {
        "AllDates": dateTime,            # Sets DateTimeOriginal, CreateDate, ModifyDate
        "Keys:CreationDate": date.isoformat(),
        "Artist": author,
        "Author": author,
        "Make": camera_make,
        "Model": camera_model,
    }

    if description:
        tags["Description"] = description
        tags["ImageDescription"] = description
        tags["Title"] = description
        tags["ItemList:Title"] = description
        tags["ItemList:Description"] = description

    if lat != 0.0 or lng != 0.0:
        coordinates = f"{lat:+013.9f}{lng:+014.9f}{altitude:+.3f}/"
        tags["Keys:GPSCoordinates"] = coordinates
        tags["UserData:GPSCoordinates"] = coordinates
        # Standard GPS tags
        tags["GPSLatitude"] = lat
        tags["GPSLongitude"] = lng
        tags["GPSAltitude"] = abs(altitude)
        tags["GPSAltitudeRef#"] = 1 if altitude < 0 else 0

    if software: # example : CapCut / adobe / Da Vinci...
        tags["Software"] = software
        tags["CreatorTool"] = software
        tags["HandlerDescription"] = software

    _write_exiftool_tags(filepath, tags, exiftool_path, ("-api", "QuickTimeUTC=1"))

def get_content_identifier(filepath, exiftool_path=None):
    """Read an embedded identifier from either half of a Live Photo."""
    if get_exiftool_path(exiftool_path):
        result = _run_exiftool(filepath, ["-j", "-G1", "-Apple:ContentIdentifier", "-Keys:ContentIdentifier"], exiftool_path)
        metadata = json.loads(result.stdout.decode("utf-8"))
        identifiers = {
            value.strip() for key, value in metadata[0].items()
            if key.endswith(":ContentIdentifier") and isinstance(value, str) and value.strip()
        }
        if len(identifiers) > 1:
            raise ValueError(f"Conflicting Live Photo identifiers: {os.path.basename(filepath)}")
        if identifiers:
            return next(iter(identifiers))
    xattr_path = shutil.which("xattr") if platform.system() == "Darwin" else None
    if xattr_path:
        result = subprocess.run([xattr_path, "-p", "com.apple.quicktime.content.identifier", os.path.abspath(filepath)], capture_output=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace").strip() or None
    return None

def set_content_identifier(filepath, identifier, exiftool_path=None):
    """Sets a copied Apple Live Photo identifier on a video file."""
    if not isinstance(identifier, str) or not identifier.strip() or any(character in identifier for character in "\r\n\0"):
        raise ValueError("Invalid Live Photo identifier")
    _write_exiftool_tags(filepath, {"Keys:ContentIdentifier": identifier.strip()}, exiftool_path)
    if get_content_identifier(filepath, exiftool_path) != identifier.strip():
        raise RuntimeError("ExifTool did not preserve the requested Live Photo identifier")