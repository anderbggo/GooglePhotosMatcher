"""Interface texts and Spanish translations of log messages."""

TEXT = {
    "en": {
        "theme": "Theme", "language": "Language", "system": "System", "light": "Light", "dark": "Dark",
        "folder": "Google Takeout folder", "browse": "Browse", "match": "Match", "preview": "Preview",
        "cancel": "Cancel", "matched": "Matched", "errors": "Errors",
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
        "force": "Force match", "force_tip": "Retry failed files with riskier fixes",
        "force_title": "Force match the failed files?",
        "force_message": "GPMatcher will retry the files that failed using riskier fixes:\n\n\u2022 Rename files whose content belongs to another format (for example, a PNG named .jpg).\n\u2022 Ignore minor metadata errors, rebuild damaged metadata or, as a last resort, remove the metadata already embedded in the file (camera, lens, etc.) before writing the Google Photos data.\n\u2022 Use the only file with the same name but another extension, and discard invalid GPS or descriptions.\n\nRisky fixes are tried on a temporary copy first. Forced results are saved in MatchedMedia/ForcedMatches so you can review them. Files that still fail stay in their folder as unmatched.",
        "force_continue": "Force match",
    },
    "es": {
        "theme": "Tema", "language": "Idioma", "system": "Sistema", "light": "Claro", "dark": "Oscuro",
        "folder": "Carpeta de Google Takeout", "browse": "Elegir carpeta", "match": "Restaurar", "preview": "Vista previa",
        "cancel": "Cancelar", "matched": "Restaurados", "errors": "Errores",
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
        "force": "Forzar", "force_tip": "Reintentar los archivos fallidos con arreglos m\u00e1s arriesgados",
        "force_title": "\u00bfForzar los archivos fallidos?",
        "force_message": "GPMatcher reintentar\u00e1 los archivos que fallaron con arreglos m\u00e1s arriesgados:\n\n\u2022 Renombrar archivos cuyo contenido es de otro formato (por ejemplo, un PNG llamado .jpg).\n\u2022 Ignorar errores menores de metadatos, reconstruir metadatos da\u00f1ados o, como \u00faltimo recurso, borrar los metadatos que ya tiene el archivo (c\u00e1mara, objetivo, etc.) antes de escribir los de Google Fotos.\n\u2022 Usar el \u00fanico archivo con el mismo nombre y otra extensi\u00f3n, y descartar GPS o descripciones no v\u00e1lidos.\n\nLos arreglos arriesgados se prueban antes en una copia temporal. Los resultados forzados se guardan en MatchedMedia/ForcedMatches para que puedas revisarlos. Los que sigan fallando se quedar\u00e1n en su carpeta como sin pareja.",
        "force_continue": "Forzar",
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
    "Live Photo check skipped: ": "Comprobaci\u00f3n Live Photo omitida: ",
    "ExifTool failed: ": "Error de ExifTool: ", "ExifTool could not write requested metadata: ": "ExifTool no pudo escribir los metadatos: ",
    "Creation time unchanged: ": "Fecha de creaci\u00f3n sin modificar: ", "Scanning: ": "Analizando: ",
    "Could not open browser: ": "No se pudo abrir el navegador: ",
    "Could not save preferences: ": "No se pudieron guardar las preferencias: ",
    "Force match failed: ": "Forzado fallido: ", "Force match: ": "Forzado: ",
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
