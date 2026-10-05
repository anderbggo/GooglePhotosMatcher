import ctypes
import json
import locale
import os
import platform
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path


LIGHT_PALETTE = {
    "bg": "#F2F4F5", "panel": "#FFFFFF", "panel_alt": "#E9EEF0",
    "text": "#202D32", "muted": "#596B73", "accent": "#0E7A62",
    "accent_soft": "#075941", "accent_hover": "#09654F", "on_accent": "#FFFFFF",
    "success": "#147451", "danger": "#B3384B", "warning": "#94621B",
    "input_bg": "#F5F7F8", "line": "#D8E0E3", "hover": "#D5E9E2",
    "support_bg": "#FBE9ED", "support_text": "#A3344D",
}
DARK_PALETTE = {
    "bg": "#111719", "panel": "#1B2327", "panel_alt": "#2B383E",
    "text": "#E8EFF1", "muted": "#ACBBC1", "accent": "#64D9AE",
    "accent_soft": "#3CB98C", "accent_hover": "#8BEBC8", "on_accent": "#10271D",
    "success": "#78DDB2", "danger": "#FF9DAD", "warning": "#EAC379",
    "input_bg": "#151D21", "line": "#3D4D54", "hover": "#324D44",
    "support_bg": "#3D2730", "support_text": "#FFADBE",
}
PALETTES = {"light": LIGHT_PALETTE, "dark": DARK_PALETTE}
THEME_OPTIONS = ("system", "light", "dark")
LANGUAGE_OPTIONS = ("system", "en", "es")
TEXT = {
    "en": {
        "theme": "Theme", "language": "Language", "system": "System", "light": "Light", "dark": "Dark",
        "folder": "Google Takeout folder", "browse": "Browse", "match": "Match", "preview": "Preview",
        "cancel": "Cancel", "matched": "Matched", "existing": "Already done", "errors": "Errors",
        "unmatched": "Unmatched", "activity": "Activity", "ready": "Ready", "scanning": "Scanning...",
        "finishing": "Finishing current file...", "invalid_folder": "Invalid Takeout folder",
        "cancelled": "Cancelled", "preview_done": "Preview complete", "done": "Restoration complete",
        "results": "Open results", "report": "Open report", "about": "\u24d8  About", "support": "\u2661  Support me",
        "about_tip": "About Google Photos Matcher", "support_tip": "Support the developer",
        "theme_tip": "Choose the app theme", "language_tip": "Choose the app language",
        "browser_failed": "Could not open browser: {detail}", "preferences_failed": "Could not save preferences: {detail}",
        "backup_title": "A backup is a good idea",
        "backup_message": "Make a backup of this folder before continuing. Future-you is a big fan of backups.\n\nGPMatcher will edit the media, move restored files into MatchedMedia and originals of edited photos into EditedRaw, and delete their JSON sidecars. Failed files and their JSON stay in their original folders.\n\nA failed write may already have changed some metadata. GPMatcher restores dates, not the past.",
        "backup_continue": "Continue and match",
    },
    "es": {
        "theme": "Tema", "language": "Idioma", "system": "Sistema", "light": "Claro", "dark": "Oscuro",
        "folder": "Carpeta de Google Takeout", "browse": "Elegir carpeta", "match": "Restaurar", "preview": "Vista previa",
        "cancel": "Cancelar", "matched": "Restaurados", "existing": "Ya restaurados", "errors": "Errores",
        "unmatched": "Sin pareja", "activity": "Actividad", "ready": "Listo", "scanning": "Analizando...",
        "finishing": "Finalizando archivo actual...", "invalid_folder": "Carpeta de Takeout no v\u00e1lida",
        "cancelled": "Cancelado", "preview_done": "Vista previa completada", "done": "Restauraci\u00f3n completada",
        "results": "Abrir resultados", "report": "Abrir informe", "about": "\u24d8  Acerca de", "support": "\u2661  Apoyarme",
        "about_tip": "Acerca de Google Photos Matcher", "support_tip": "Apoyar al desarrollador",
        "theme_tip": "Elegir el tema de la aplicaci\u00f3n", "language_tip": "Elegir el idioma de la aplicaci\u00f3n",
        "browser_failed": "No se pudo abrir el navegador: {detail}", "preferences_failed": "No se pudieron guardar las preferencias: {detail}",
        "backup_title": "Una copia de seguridad viene bien",
        "backup_message": "Recomendamos hacer una copia de esta carpeta antes de continuar. Tu yo del futuro te lo agradecer\u00e1; quiz\u00e1 hasta te invite a un caf\u00e9.\n\nGPMatcher modificar\u00e1 los archivos, guardar\u00e1 los restaurados en MatchedMedia y los originales de fotos editadas en EditedRaw, y borrar\u00e1 sus JSON. Los que fallen se quedar\u00e1n en su carpeta con su JSON.\n\nUn fallo de escritura puede dejar metadatos cambiados. Restauramos fechas, no viajamos en el tiempo.",
        "backup_continue": "Continuar y restaurar",
    },
}
SPANISH_MESSAGES = {
    "No JSON files found in the selected folder": "No se encontraron archivos JSON en la carpeta seleccionada",
    "Select the original Takeout folder, not an output folder": "Selecciona la carpeta original de Takeout, no una carpeta de resultados",
    "Missing photo timestamp": "Falta la fecha de la foto", "Invalid photo timestamp": "Fecha de la foto no v\u00e1lida",
    "Invalid GPS coordinates": "Coordenadas GPS no v\u00e1lidas", "Invalid description": "Descripci\u00f3n no v\u00e1lida",
    "Invalid JSON title": "T\u00edtulo del JSON no v\u00e1lido", "JSON metadata must be an object": "Los metadatos JSON deben ser un objeto",
    "Not a photo/video metadata sidecar": "No es un JSON de metadatos de foto o v\u00eddeo",
    "Cancelled before writing": "Cancelado antes de escribir",
    "No confirmed metadata match; original left untouched": "Sin metadatos asociados; original sin modificar",
    "Multiple companion videos; automatic pairing skipped": "Varios v\u00eddeos posibles; no se han asociado autom\u00e1ticamente",
    "Live Photo identifiers are missing or different; video left untouched": "Identificadores Live Photo ausentes o distintos; v\u00eddeo sin modificar",
    "Live Photo identifier changed during metadata writing; output not published": "El identificador Live Photo ha cambiado; resultado no publicado",
    "Live Photo identifier changed during metadata writing; media left in original folder": "El identificador Live Photo ha cambiado; archivos en su carpeta original",
    "MKV metadata cannot be written by ExifTool; original and JSON left untouched": "ExifTool no puede escribir metadatos MKV; original y JSON sin modificar",
    "ExifTool is required for this file. Use the standalone build, or install ExifTool on PATH when running the Python source.": "Este archivo necesita ExifTool. Usa el EXE completo o instala ExifTool en PATH si ejecutas el c\u00f3digo Python.",
}
SPANISH_PREFIXES = {
    "No unambiguous media match for ": "No se pudo identificar una pareja \u00fanica para ",
    "Ambiguous match: ": "Coincidencia ambigua: ", "Duplicate sidecar for ": "JSON duplicado para ",
    "Conflicting JSON sidecars for ": "JSON contradictorios para ",
    "Different output already exists; nothing overwritten: ": "Ya existe un resultado diferente; no se ha sobrescrito: ",
    "Output already exists; nothing overwritten: ": "Ya existe un resultado; no se ha sobrescrito: ",
    "Live Photo check skipped: ": "Comprobaci\u00f3n Live Photo omitida: ",
    "ExifTool failed: ": "Error de ExifTool: ", "ExifTool could not write requested metadata: ": "ExifTool no pudo escribir los metadatos: ",
    "Creation time unchanged: ": "Fecha de creaci\u00f3n sin modificar: ", "Scanning: ": "Analizando: ",
    "Could not open browser: ": "No se pudo abrir el navegador: ",
    "Could not save preferences: ": "No se pudieron guardar las preferencias: ",
}
SPANISH_LOG_STATUS = {"RESTORED": "RESTAURADO", "ALREADY_RESTORED": "YA RESTAURADO", "PREVIEW": "VISTA PREVIA", "ERROR": "ERROR", "SKIPPED": "OMITIDO", "CANCELLED": "CANCELADO", "UNMATCHED": "SIN PAREJA", "Report": "Informe"}


def text(language, key, **values):
    return TEXT.get(language, TEXT["en"])[key].format(**values)


def format_number(value, language):
    formatted = f"{value:,}"
    return formatted.replace(",", ".") if language == "es" else formatted


def localize_message(message, language):
    if language != "es":
        return message
    if message in SPANISH_MESSAGES:
        return SPANISH_MESSAGES[message]
    for prefix, translated in SPANISH_PREFIXES.items():
        if message.startswith(prefix):
            return translated + message[len(prefix):]
    status, separator, content = message.partition(": ")
    if separator and status in SPANISH_LOG_STATUS:
        filename, detail_separator, details = content.partition(" | ")
        if detail_separator:
            content = filename + detail_separator + localize_message(details, language)
        elif status == "ERROR":
            content = localize_message(content, language)
        return SPANISH_LOG_STATUS[status] + separator + content
    return message


def system_language():
    if platform.system() == "Windows":
        try:
            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if language_id:
                return "es" if language_id & 0x3FF == 0x0A else "en"
        except (AttributeError, OSError):
            pass
    elif platform.system() == "Darwin":
        try:
            result = subprocess.run(["defaults", "export", "-g", "-"], capture_output=True, timeout=3)
            if result.returncode == 0:
                languages = plistlib.loads(result.stdout).get("AppleLanguages", [])
                if languages:
                    return "es" if str(languages[0]).casefold().startswith("es") else "en"
        except (OSError, ValueError, subprocess.SubprocessError, plistlib.InvalidFileException):
            pass
    language = next((os.environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG") if os.environ.get(key)), None)
    if not language:
        try:
            language = locale.getlocale()[0] or "en"
        except ValueError:
            language = "en"
    return "es" if language.casefold().startswith("es") else "en"


def system_theme():
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return "dark" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0 else "light"
        except (OSError, ImportError):
            return "light"
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, timeout=3)
            return "dark" if result.returncode == 0 and result.stdout.strip().lower() == b"dark" else "light"
        except (OSError, subprocess.SubprocessError):
            return "light"
    if "dark" in os.environ.get("GTK_THEME", "").casefold():
        return "dark"
    if shutil.which("gsettings"):
        try:
            result = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], capture_output=True, timeout=3)
            if result.returncode == 0 and b"prefer-dark" in result.stdout:
                return "dark"
        except (OSError, subprocess.SubprocessError):
            pass
    return "light"


def preference_path():
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "GPMatcher" / "preferences.json"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "GPMatcher" / "preferences.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gpmatcher" / "preferences.json"


def validate_preferences(values):
    if not isinstance(values, dict):
        values = {}
    return {"theme": values.get("theme") if values.get("theme") in THEME_OPTIONS else "system", "language": values.get("language") if values.get("language") in LANGUAGE_OPTIONS else "system"}


def load_preferences(path=None):
    try:
        values = json.loads((path or preference_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        values = {}
    return validate_preferences(values)


def save_preferences(values, path=None):
    path = path or preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix="preferences-", suffix=".json", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(validate_preferences(values), stream, indent=2)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_preferences(values):
    values = validate_preferences(values)
    return (system_theme() if values["theme"] == "system" else values["theme"], system_language() if values["language"] == "system" else values["language"])