import os
import json
import PySimpleGUI as sg
from auxFunctions import searchMedia, fixTitle, set_photo_metadata, set_video_metadata, setWindowsTime
def log(window, msg):
    """Send a log message to the UI"""
    window.write_event_value('-LOG-', msg)
    print(msg)

def mainProcess(browserPath, window, editedW, exiftoolPath=None):
    # Supported extensions
    piexifCodecs = [k.casefold() for k in ['TIF', 'TIFF', 'JPEG', 'JPG']] #TODO: PNG ?
    videoCodecs = [k.casefold() for k in ['MP4', 'MOV', '3GP', 'M4V', 'MKV']]

    mediaMoved: dict[str, list[str]] = {}
    root_fixed = os.path.join(browserPath, "MatchedMedia")
    root_nonEdited = os.path.join(browserPath, "EditedRaw")
    
    errorCounter = 0
    successCounter = 0
    editedWord = editedW or "editado"

    try:
        json_files = []
        for root, dirs, files in os.walk(browserPath):
            # Exclude output folders from search
            dirs[:] = [d for d in dirs if os.path.join(root, d) not in (root_fixed, root_nonEdited)]
            file: str = "" 
            for file in files:
                if file.endswith(".json"):
                    json_files.append(os.path.join(root, file))
        
        # Sort by filename length to process originals before duplicates
        json_files.sort(key=lambda s: len(os.path.basename(s)))
    except Exception as e:
        window.write_event_value('-UPDATE_ERROR-', "Invalid directory selected")
        return

    if not json_files:
        window.write_event_value('-UPDATE_ERROR-', "No JSON files found")
        return

    total_files = len(json_files)
    for index, json_path in enumerate(json_files):
        try:
            with open(json_path, encoding="utf8") as f:
                data = json.load(f)
        except Exception:
            errorCounter += 1
            continue

        progress = round(((index + 1) / total_files) * 100, 2)
        window.write_event_value('-UPDATE_PROGRESS-', (progress, os.path.basename(json_path)))

        if 'title' not in data:
            log(window, f"SKIP (no title): {os.path.basename(json_path)}")
            continue

        # Support both photoTakenTime and photoLastModifiedTime (supplemental-metadata)
        has_time = 'photoTakenTime' in data or 'photoLastModifiedTime' in data
        if not has_time:
            log(window, f"SKIP (no timestamp): {os.path.basename(json_path)}")
            continue

        titleOriginal:str = data['title']
        # Clean supplemental metadata suffixes
        for ext in ['.supplemental-metadata', '.supplemental-metada']:
            titleOriginal = titleOriginal.replace(ext, '')

        current_dir = os.path.dirname(json_path)
        rel_dir = os.path.relpath(current_dir, browserPath)
        if rel_dir == ".": rel_dir = ""
            
        fixedMediaPath = os.path.join(root_fixed, rel_dir)
        nonEditedMediaPath = os.path.join(root_nonEdited, rel_dir)
        
        os.makedirs(fixedMediaPath, exist_ok=True)
        os.makedirs(nonEditedMediaPath, exist_ok=True)

        # Handle Google Photos hidden suffixes
        parts = titleOriginal.rsplit('.', 1)
        base_candidates = [titleOriginal]
        if len(parts) == 2:
            for suffix in ['_PORTRAIT', 'PORTRAIT', '_NFNR', '_MFNR']:
                base_candidates.append(f"{parts[0]}{suffix}.{parts[1]}")
            for suffix in ['_PORTRAIT', 'PORTRAIT', '_NFNR', '_MFNR']:
                if parts[0].endswith(suffix):
                    base_candidates.append(f"{parts[0][:-len(suffix)]}.{parts[1]}")

        if current_dir not in mediaMoved:
            mediaMoved[current_dir] = []

        title = "None"
        editedTitle = None
        originalTitle = None
        for candidate in base_candidates:
            editedTitle, originalTitle = searchMedia(current_dir, candidate, mediaMoved[current_dir], nonEditedMediaPath, editedWord)
            if editedTitle or originalTitle:
                titleOriginal = candidate
                break

        # Determine which file goes to MatchedMedia
        # If there's an edited version: edited -> MatchedMedia, original -> EditedRaw
        # If only original: original -> MatchedMedia
        title = editedTitle or originalTitle
        raw_title = originalTitle if editedTitle else None

        filepath = None
        already_moved = False
        
        if not title:
            # Check if already moved (exact match or prefix match for truncated names)
            for cand in base_candidates:
                if os.path.exists(os.path.join(fixedMediaPath, cand)):
                    title = cand
                    filepath = os.path.join(fixedMediaPath, title)
                    already_moved = True
                    break
            # Try prefix match in MatchedMedia for truncated filenames
            if not already_moved:
                import glob
                for cand in base_candidates:
                    cand_clean = fixTitle(cand)
                    if '.' in cand_clean:
                        cand_base, cand_ext = cand_clean.rsplit('.', 1)
                        safe_prefix = cand_base[:47].replace('[', '[[]').replace(']', '[]]')
                        matches = glob.glob(os.path.join(fixedMediaPath, f"{safe_prefix}*.{cand_ext}"))
                        for m in matches:
                            if not m.endswith('.json'):
                                title = os.path.basename(m)
                                filepath = m
                                already_moved = True
                                break
                    if already_moved:
                        break
            if not already_moved:
                log(window, f"NOT FOUND: {titleOriginal}")
                errorCounter += 1
                continue
        else:
            filepath = os.path.join(current_dir, title)

        
        try:
            # set data to dict for IDE and the method .get 
            data: dict = data 
            
            # Use photoTakenTime, fallback to photoLastModifiedTime (supplemental-metadata)
            photo_info: dict = data.get('photoTakenTime', data.get('photoLastModifiedTime', {}))
            
            timeStamp = int(photo_info.get('timestamp', 0))
         
            # Location of the photo
            geoData: dict = data.get('geoData', {})
            lat = float(geoData.get('latitude', 0.0))
            lng = float(geoData.get('longitude', 0.0))
            alt = float(geoData.get('altitude', 0.0))
            
            description = data.get('description', '')

            origin = data.get('googlePhotosOrigin', {})
            
            # Check if it if a dict for Type Hinting (more particulary .get)
            if isinstance(origin, dict):
                mobile = origin.get('mobileUpload', {})
                if isinstance(mobile, dict):
                    folder = mobile.get('deviceFolder', {})
                    if isinstance(folder, dict):
                        camera_make = folder.get('localFolderName', '')
                    else:
                        camera_make = ""
                else:
                    camera_make = ""
            else:
                camera_make = ""
           
            camera_model = "" 
            software = "" 

            ext = title.rsplit('.', 1)[1].casefold() if '.' in title else ""


            # Set metadatas
            if ext in piexifCodecs:
                set_photo_metadata(filepath, lat, lng, alt, timeStamp, description)
            elif ext in videoCodecs:
                try:
                    set_video_metadata(filepath, lat, lng, alt, timeStamp, description, camera_make, camera_model, "", software, exiftool_path=exiftoolPath)
                except FileNotFoundError as e:
                    log(window, str(e))
                    errorCounter += 1
                    continue
                except Exception as e:
                    log(window, f"VIDEO METADATA ERROR: {e}")
                    errorCounter += 1
                    continue

            setWindowsTime(filepath, timeStamp)

            if not already_moved:
                # Move edited (or only) file to MatchedMedia
                os.replace(filepath, os.path.join(fixedMediaPath, title))
                mediaMoved[current_dir].append(title)
                
                # Move original to EditedRaw (only when an edited version exists)
                if raw_title and raw_title != title:
                    raw_path = os.path.join(current_dir, raw_title)
                    if os.path.exists(raw_path):
                        os.replace(raw_path, os.path.join(nonEditedMediaPath, raw_title))
                        mediaMoved[current_dir].append(raw_title)
                
            os.remove(json_path)
            successCounter += 1
            
        except Exception as e:
            log(window, f"ERROR {title}: {e}")
            errorCounter += 1
            continue

    window.write_event_value('-UPDATE_DONE-', (successCounter, errorCounter))