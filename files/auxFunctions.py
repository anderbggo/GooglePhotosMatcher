import os
import time
from datetime import datetime
import piexif
from win32_setctime import setctime
from fractions import Fraction


# Function to search media associated to the JSON
def searchMedia(path, title, mediaMoved, nonEdited, editedWord):
    title = fixTitle(title)
    realTitle = str(title.rsplit('.', 1)[0] + "-" + editedWord + "." + title.rsplit('.', 1)[1])
    filepath = path + "\\" + realTitle  # First we check if exists an edited version of the image
    if not os.path.exists(filepath):
        realTitle = str(title.rsplit('.', 1)[0] + "(1)." + title.rsplit('.', 1)[1])
        filepath = path + "\\" + realTitle  # First we check if exists an edited version of the image
        if not os.path.exists(filepath) or os.path.exists(path + "\\" + title + "(1).json"):
            realTitle = title
            filepath = path + "\\" + realTitle  # If not, check if exists the path with the same name
            if not os.path.exists(filepath):
                realTitle = checkIfSameName(title, title, mediaMoved, 1)  # If not, check if exists the path to the same name adding (1), (2), etc
                filepath = str(path + "\\" + realTitle)
                if not os.path.exists(filepath):
                    title = (title.rsplit('.', 1)[0])[:47] + "." + title.rsplit('.', 1)[1]  # Sometimes title is limited to 47 characters, check also that
                    realTitle = str(title.rsplit('.', 1)[0] + "-editado." + title.rsplit('.', 1)[1])
                    filepath = path + "\\" + realTitle
                    if not os.path.exists(filepath):
                        realTitle = str(title.rsplit('.', 1)[0] + "(1)." + title.rsplit('.', 1)[1])
                        filepath = path + "\\" + realTitle
                        if not os.path.exists(filepath):
                            realTitle = title
                            filepath = path + "\\" + realTitle
                            if not os.path.exists(filepath):
                                realTitle = checkIfSameName(title, title, mediaMoved, 1)
                                filepath = path + "\\" + realTitle
                                if not os.path.exists(filepath):  # If path not found, return null
                                    realTitle = None
                        else:
                            filepath = path + "\\" + title  # Move original media to another folder
                            os.replace(filepath, nonEdited + "\\" + title)
                    else:
                        filepath = path + "\\" + title  # Move original media to another folder
                        os.replace(filepath, nonEdited + "\\" + title)
        else:
            filepath = path + "\\" + title  # Move original media to another folder
            os.replace(filepath, nonEdited + "\\" + title)
    else:
        filepath = path + "\\" + title  # Move original media to another folder
        os.replace(filepath, nonEdited + "\\" + title)

    return str(realTitle)


# Supress incompatible characters
def fixTitle(title):
    return str(title).replace("%", "").replace("<", "").replace(">", "").replace("=", "").replace(":", "").replace("?","").replace(
        "¿", "").replace("*", "").replace("#", "").replace("&", "").replace("{", "").replace("}", "").replace("\\", "").replace(
        "@", "").replace("!", "").replace("¿", "").replace("+", "").replace("|", "").replace("\"", "").replace("\'", "")

# Recursive function to search name if its repeated
def checkIfSameName(title, titleFixed, mediaMoved, recursionTime):
    if titleFixed in mediaMoved:
        titleFixed = title.rsplit('.', 1)[0] + "(" + str(recursionTime) + ")" + "." + title.rsplit('.', 1)[1]
        return checkIfSameName(title, titleFixed, mediaMoved, recursionTime + 1)
    else:
        return titleFixed

def createFolders(fixed, nonEdited):
    if not os.path.exists(fixed):
        os.mkdir(fixed)

    if not os.path.exists(nonEdited):
        os.mkdir(nonEdited)

def setWindowsTime(filepath, timeStamp):
    setctime(filepath, timeStamp)  # Set windows file creation time
    date = datetime.fromtimestamp(timeStamp)
    modTime = time.mktime(date.timetuple())
    os.utime(filepath, (modTime, modTime))  # Set windows file modification time

def to_deg(value, loc):
    """convert decimal coordinates into degrees, munutes and seconds tuple
    Keyword arguments: value is float gps-value, loc is direction list ["S", "N"] or ["W", "E"]
    return: tuple like (25, 13, 48.343 ,'N')
    """
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
    """convert a number to rational
    Keyword arguments: number
    return: tuple like (1, 2), (numerator, denominator)
    """
    f = Fraction(str(number))
    return (f.numerator, f.denominator)


def set_EXIF(filepath, lat, lng, altitude, timeStamp):
    exif_dict = piexif.load(filepath)

    dateTime = datetime.fromtimestamp(timeStamp).strftime("%Y:%m:%d %H:%M:%S")  # Create date object
    exif_dict['0th'][piexif.ImageIFD.DateTime] = dateTime
    exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = dateTime
    exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = dateTime

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, filepath)


    try:
        exif_dict = piexif.load(filepath)
        lat_deg = to_deg(lat, ["S", "N"])
        lng_deg = to_deg(lng, ["W", "E"])

        exiv_lat = (change_to_rational(lat_deg[0]), change_to_rational(lat_deg[1]), change_to_rational(lat_deg[2]))
        exiv_lng = (change_to_rational(lng_deg[0]), change_to_rational(lng_deg[1]), change_to_rational(lng_deg[2]))

        gps_ifd = {
            piexif.GPSIFD.GPSVersionID: (2, 0, 0, 0),
            piexif.GPSIFD.GPSAltitudeRef: 1,
            piexif.GPSIFD.GPSAltitude: change_to_rational(round(altitude, 2)),
            piexif.GPSIFD.GPSLatitudeRef: lat_deg[3],
            piexif.GPSIFD.GPSLatitude: exiv_lat,
            piexif.GPSIFD.GPSLongitudeRef: lng_deg[3],
            piexif.GPSIFD.GPSLongitude: exiv_lng,
        }

        exif_dict['GPS'] = gps_ifd

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, filepath)

    except Exception as e:
        print("Coordinates not settled")
        pass


