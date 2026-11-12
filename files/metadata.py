"""Writes dates, GPS and descriptions into media files."""
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from fractions import Fraction

import piexif

import exiftool_runner

if platform.system() == "Windows":
    from win32_setctime import setctime
else:
    setctime = None


def parse_filename_timestamp(filename):
    """Extract a Unix timestamp from standard camera, smartphone, and messaging app filename patterns."""
    if not filename:
        return None
    patterns = [
        # Camera / Pixel / Samsung / Snapchat / Screenshots
        r"(?:IMG|PXL|VID|SAM|WP|AUD|Screenshot|ScreenShot|Snapchat)[_-](\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})",
        # Signal / Telegram / Messaging / Generic
        r"(?:signal|photo|video|Telegram|Screen_Recording)?[_-]?(\d{4})[-_](\d{2})[-_](\d{2})[ _-](\d{2})[.:_-](\d{2})[.:_-](\d{2})",
        r"(?<!\d)(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?!\d)",
        # WordPress / Samsung alternate
        r"wp-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            groups = [g for g in match.groups() if g is not None]
            if len(groups) >= 6:
                y, m, d, h, mn, s = map(int, groups[-6:])
                if 1970 <= y <= 2040 and 1 <= m <= 12 and 1 <= d <= 31 and 0 <= h <= 23 and 0 <= mn <= 59 and 0 <= s <= 59:
                    try:
                        dt = datetime(y, m, d, h, mn, s).astimezone()
                        return int(dt.timestamp())
                    except (ValueError, OverflowError):
                        continue
    date_patterns = [
        # WhatsApp: IMG-20201015-WA0004.jpg, VID-20201015-WA0002.mp4
        r"(?:IMG|VID)[_-](\d{4})(\d{2})(\d{2})[_-]WA\d+",
        # Standard date-only prefixes
        r"(?:IMG|PXL|VID|SAM|WA)[_-](\d{4})(\d{2})(\d{2})",
        r"(?<!\d)(\d{4})[-_](\d{2})[-_](\d{2})(?!\d)",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            y, m, d = map(int, match.groups()[:3])
            if 1970 <= y <= 2040 and 1 <= m <= 12 and 1 <= d <= 31:
                try:
                    dt = datetime(y, m, d, 12, 0, 0).astimezone()
                    return int(dt.timestamp())
                except (ValueError, OverflowError):
                    continue

    epoch_patterns = [
        # Snapchat / Facebook / Instant Messenger: Snapchat-1482486059.mp4, 1482486059123.jpg
        r"(?:Snapchat|Facebook|FB_IMG)[_-]([1-2]\d{9})(?!\d)",
        r"(?<!\d)([1-2]\d{9})(?!\d)",
        r"(?<!\d)([1-2]\d{12})(?!\d)",
    ]
    for pattern in epoch_patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            raw_ts = int(match.group(1))
            if raw_ts > 100_000_000_000:
                raw_ts //= 1000
            if 631152000 <= raw_ts <= 2208988800:
                return raw_ts
    return None


def get_container_datetime(filepath, exiftool_path=None):
    """Read embedded creation or modification date from image/video header as last resort."""
    if not os.path.isfile(filepath):
        return None
    try:
        ext = os.path.splitext(filepath)[1].casefold()
        if ext in {".jpg", ".jpeg"}:
            try:
                exif_dict = piexif.load(filepath)
                for ifd in ("Exif", "0th"):
                    for tag in (piexif.ExifIFD.DateTimeOriginal, piexif.ImageIFD.DateTime):
                        raw_date = exif_dict.get(ifd, {}).get(tag)
                        if raw_date and isinstance(raw_date, bytes):
                            text_date = raw_date.decode("latin1", errors="ignore").strip()
                            dt = datetime.strptime(text_date, "%Y:%m:%d %H:%M:%S").astimezone()
                            ts = int(dt.timestamp())
                            if ts > 0:
                                return ts
            except Exception:
                pass
        if exiftool_runner.get_exiftool_path(exiftool_path):
            result = exiftool_runner.run_exiftool(filepath, ["-j", "-DateTimeOriginal", "-CreateDate", "-CreationDate"], exiftool_path)
            items = json.loads(result.stdout.decode("utf-8"))
            if items and isinstance(items, list):
                for key in ("DateTimeOriginal", "CreateDate", "CreationDate"):
                    val = items[0].get(key)
                    if isinstance(val, str) and len(val) >= 19:
                        try:
                            clean_str = val[:19]
                            dt = datetime.strptime(clean_str, "%Y:%m:%d %H:%M:%S").astimezone()
                            ts = int(dt.timestamp())
                            if ts > 0:
                                return ts
                        except Exception:
                            continue
    except Exception:
        pass
    return None


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


def set_image_metadata(filepath, lat, lng, altitude, timeStamp, description="", exiftool_path=None, extra_options=()):
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
    exiftool_runner.write_exiftool_tags(filepath, tags, exiftool_path, ("-api", "LargeFileSupport=1", *extra_options))


def set_video_metadata(filepath, lat, lng, altitude, timeStamp, description="", camera_make="", camera_model="", author="", software="", exiftool_path=None, extra_options=()):
    """Injects metadata into video files using ExifTool"""
    date = datetime.fromtimestamp(timeStamp).astimezone()
    dateTime = date.strftime("%Y:%m:%d %H:%M:%S")

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
        tags["GPSLatitude"] = lat
        tags["GPSLongitude"] = lng
        tags["GPSAltitude"] = abs(altitude)
        tags["GPSAltitudeRef#"] = 1 if altitude < 0 else 0

    if software:  # example : CapCut / adobe / Da Vinci...
        tags["Software"] = software
        tags["CreatorTool"] = software
        tags["HandlerDescription"] = software

    exiftool_runner.write_exiftool_tags(filepath, tags, exiftool_path, ("-api", "QuickTimeUTC=1", "-api", "LargeFileSupport=1", *extra_options))


def get_content_identifier(filepath, exiftool_path=None):
    """Read an embedded identifier from either half of a Live Photo."""
    if exiftool_runner.get_exiftool_path(exiftool_path):
        result = exiftool_runner.run_exiftool(filepath, ["-j", "-G1", "-Apple:ContentIdentifier", "-Keys:ContentIdentifier", "-XMP:ContentIdentifier"], exiftool_path)
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
    """Sets an Apple Live Photo identifier on a video or image file."""
    if not isinstance(identifier, str) or not identifier.strip() or any(character in identifier for character in "\r\n\0"):
        raise ValueError("Invalid Live Photo identifier")
    identifier = identifier.strip()
    ext = os.path.splitext(filepath)[1].casefold()
    if ext in {".mov", ".mp4"}:
        tags = {"Keys:ContentIdentifier": identifier}
        exiftool_runner.write_exiftool_tags(filepath, tags, exiftool_path, extra_options=("-m", "-api", "LargeFileSupport=1"))
    else:
        try:
            tags = {"Apple:ContentIdentifier": identifier, "XMP:ContentIdentifier": identifier}
            exiftool_runner.write_exiftool_tags(filepath, tags, exiftool_path, extra_options=("-m", "-api", "LargeFileSupport=1"))
        except Exception:
            tags = {"XMP:ContentIdentifier": identifier}
            exiftool_runner.write_exiftool_tags(filepath, tags, exiftool_path, extra_options=("-m", "-api", "LargeFileSupport=1"))
    if get_content_identifier(filepath, exiftool_path) != identifier:
        raise RuntimeError("ExifTool did not preserve the requested Live Photo identifier")
