import os
import sys
import time
import piexif
import subprocess
from datetime import datetime
from win32_setctime import setctime
from fractions import Fraction
import glob
import logging

def resource_path(relative_path: str) -> str:
    """ Finds the actual path to the resource file for PyInstaller (_MEIPASS) """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_exiftool_path(exiftool_path=None) -> str | None:
    """ Retrieves the path for the ExifTool binary """
    if exiftool_path:
        if os.path.isfile(exiftool_path):
            return exiftool_path
        raise FileNotFoundError(f"ExifTool not found at {exiftool_path}")

    if hasattr(sys, 'frozen'):
        # in .exe
        base_path = os.path.dirname(sys.executable)
    else:
        # in py
        base_path = os.path.abspath(".")
        
    exiftool_exe = os.path.join(base_path, "exiftool.exe")
    
    if os.path.isfile(exiftool_exe):
        return exiftool_exe

    return None






# MEDIA SEARCH & UTILS
def searchMedia(path, title, mediaMoved, nonEdited, editedWord):
    """Searches for the media file associated with a JSON metadata file.
    Returns (editedTitle, originalTitle) tuple.
    - editedTitle: the edited version (e.g. foto-editada.jpg), or the original if no edited exists
    - originalTitle: the original version to move to EditedRaw, or None if no edited version exists
    """
    title = fixTitle(title)
    
    def _try(name):
        """Returns the name if the file exists on disk, else None."""
        if os.path.exists(os.path.join(path, name)):
            return name
        return None
    
    base, ext = title.rsplit('.', 1) if '.' in title else (title, '')
    ext_dot = f".{ext}" if ext else ""
    
    # Build list of edited suffixes: user input first, then common ones
    edit_suffixes = []
    if editedWord:
        edit_suffixes.append(editedWord)
    common_edits = ["editado", "editada", "edited", "modifié", "modifiée", "bearbeitet", "bewerkt", "modificato", "modificata", "redigerad"]
    for s in common_edits:
        if s.casefold() not in [e.casefold() for e in edit_suffixes]:
            edit_suffixes.append(s)
    
    def _findEdited(b, e):
        """Find an edited version of the file."""
        for suffix in edit_suffixes:
            found = _try(f"{b}-{suffix}{e}")
            if found:
                return found
        return None
    
    def _findOriginal(b, e):
        """Find the original file (exact match, (1) suffix, or duplicate name)."""
        # (1) suffix
        candidate = f"{b}(1){e}"
        if _try(candidate) and not os.path.exists(os.path.join(path, f"{title}(1).json")):
            return candidate
        # Exact match
        found = _try(f"{b}{e}")
        if found:
            return found
        # Duplicate names
        found = checkIfSameName(f"{b}{e}", f"{b}{e}", mediaMoved, 1)
        if _try(found):
            return found
        return None

    # Try with full title
    edited = _findEdited(base, ext_dot)
    original = _findOriginal(base, ext_dot)
    
    if edited or original:
        return (edited, original)
    
    # Try with 47-char truncated base (Google's limit)
    trunc_base = base[:47]
    if trunc_base != base:
        edited = _findEdited(trunc_base, ext_dot)
        original = _findOriginal(trunc_base, ext_dot)
        if edited or original:
            return (edited, original)
    
    # Last resort: prefix match on filesystem (handles truncated JSON titles)
    for prefix in [base, trunc_base]:
        if not prefix:
            continue
        safe_prefix = prefix.replace('[', '[[]').replace(']', '[]]')
        matches = glob.glob(os.path.join(path, f"{safe_prefix}*{ext_dot}"))
        for match in matches:
            candidate = os.path.basename(match)
            if candidate.endswith('.json') or candidate in mediaMoved:
                continue
            return (None, candidate)
    
    return (None, None)

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
    """Sets the Windows file creation and modification timestamps"""
    try:
        setctime(filepath, timeStamp)
        date = datetime.fromtimestamp(timeStamp)
        modTime = time.mktime(date.timetuple())
        os.utime(filepath, (modTime, modTime))
    except Exception as e:
        print(f"Error setting Windows time for {filepath}: {e}")

# GPS & MATH CONVERSIONS
def to_deg(value, loc):
    """Converts decimal coordinates into (degrees, minutes, seconds, direction)"""
    if value < 0:
        loc_value = loc[0]
    elif value > 0:
        loc_value = loc[1]
    else:
        loc_value = ""
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
    try:
        exif_dict = piexif.load(filepath)
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    dateTime = datetime.fromtimestamp(timeStamp).strftime("%Y:%m:%d %H:%M:%S")
    
    if '0th' not in exif_dict: exif_dict['0th'] = {}
    if 'Exif' not in exif_dict: exif_dict['Exif'] = {}

    exif_dict['0th'][piexif.ImageIFD.DateTime] = dateTime
    exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = dateTime
    exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = dateTime

    if description:
        exif_dict['0th'][piexif.ImageIFD.ImageDescription] = description.encode('utf-8')

    # GPS Injection
    if lat != 0.0 or lng != 0.0:
        try:
            lat_deg = to_deg(lat, ["S", "N"])
            lng_deg = to_deg(lng, ["W", "E"])

            exiv_lat = (change_to_rational(lat_deg[0]), change_to_rational(lat_deg[1]), change_to_rational(lat_deg[2]))
            exiv_lng = (change_to_rational(lng_deg[0]), change_to_rational(lng_deg[1]), change_to_rational(lng_deg[2]))

            exif_dict['GPS'] = {
                piexif.GPSIFD.GPSVersionID: (2, 0, 0, 0),
                piexif.GPSIFD.GPSAltitudeRef: 1 if altitude < 0 else 0,
                piexif.GPSIFD.GPSAltitude: change_to_rational(round(abs(altitude), 2)),
                piexif.GPSIFD.GPSLatitudeRef: lat_deg[3],
                piexif.GPSIFD.GPSLatitude: exiv_lat,
                piexif.GPSIFD.GPSLongitudeRef: lng_deg[3],
                piexif.GPSIFD.GPSLongitude: exiv_lng,
            }
        except Exception:
            pass

    try:
        exif_bytes = piexif.dump(exif_dict)
    except Exception:
        # Some images (e.g. WhatsApp) have corrupted EXIF tags with wrong types.
        # Strip all non-standard tags and keep only what we set.
        clean_dict = {"0th": {}, "Exif": {}, "GPS": exif_dict.get("GPS", {}), "1st": {}, "thumbnail": None}
        clean_dict['0th'][piexif.ImageIFD.DateTime] = dateTime
        clean_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = dateTime
        clean_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = dateTime
        if description:
            clean_dict['0th'][piexif.ImageIFD.ImageDescription] = description.encode('utf-8')
        exif_bytes = piexif.dump(clean_dict)
    piexif.insert(exif_bytes, filepath)

def set_video_metadata(filepath, lat, lng, altitude, timeStamp, description="", camera_make="", camera_model="", author="", software="", exiftool_path=None):
    """Injects metadata into video files using ExifTool"""
    dateTime = datetime.fromtimestamp(timeStamp).strftime("%Y:%m:%d %H:%M:%S")

    # All the datas to transfer
    tags = {
        "AllDates": dateTime,            # Sets DateTimeOriginal, CreateDate, ModifyDate
        "Keys:CreationDate": dateTime, 
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
        tags["Keys:GPSCoordinates"] = f"{lat} {lng} {altitude}"
        tags["UserData:GPSCoordinates"] = f"{lat} {lng} {altitude}"
        # Standard GPS tags
        tags["GPSLatitude"] = lat
        tags["GPSLongitude"] = lng
        tags["GPSAltitude"] = altitude

    if software: # example : CapCut / adobe / Da Vinci...
        tags["Software"] = software
        tags["CreatorTool"] = software
        tags["HandlerDescription"] = software

    exiftool_path = get_exiftool_path(exiftool_path)
    if not exiftool_path:
        print(f"ExifTool not found, skipping metadata injection for {filepath}")
        return

    args = [exiftool_path, "-overwrite_original"]
    for key, value in tags.items():
        if value != "" and value != 0 and value != 0.0:
            args.append(f"-{key}={value}")
    args.append(filepath)

    try:
        subprocess.run(
            args,
            timeout=30,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        print(f"ExifTool TIMEOUT (30s) for {filepath}, skipping.")
    except Exception as e:
        print(f"ExifTool error for {filepath}: {e}")