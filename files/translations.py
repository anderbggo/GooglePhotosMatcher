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
        "backup_message": "Make a backup of this folder before continuing. Future-you is a big fan of backups.\n\nGPMatcher edits the originals. Restored media go into the flat MatchedMedia folder; originals of edited photos go into the flat EditedRaw folder. Takeout subfolders are not recreated. Name clashes get a number (photo(1).jpg), never overwriting existing files. Successful matches delete their JSON; failed or unmatched files keep theirs.\n\nThere is no automatic backup or undo. A failed write may have changed some metadata. GPMatcher restores dates, not the past.",
        "backup_continue": "Continue and match",
        "force": "Force match", "force_tip": "Retry errors and unmatched files with riskier fixes",
        "force_title": "Force match the remaining files?",
        "force_message": "Make a backup before continuing. GPMatcher retries failed or unmatched files with riskier fixes:\n\n\u2022 Correct extensions using the real file content (for example, a PNG named .jpg).\n\u2022 Ignore minor errors, rebuild damaged metadata or, as a last resort, remove existing metadata (camera, lens, etc.) before writing the Google Photos data.\n\u2022 Use the only file with the same name and another extension; discard invalid GPS or descriptions.\n\nMetadata repair retries use a temporary copy, replacing the original only on success. Live Photos only get the non-destructive retry.\n\nResults: MatchedMedia/ForcedMatches; edited originals: EditedRaw/ForcedMatches. Files that still fail keep their JSON, count as unmatched and appear in the CSV report. MKV files, missing dates and ambiguous matches cannot be forced.",
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
        "backup_message": "Recomendamos hacer una copia de esta carpeta antes de continuar. Tu yo del futuro te lo agradecer\u00e1; quiz\u00e1 hasta te invite a un caf\u00e9.\n\nGPMatcher modifica los originales. Los restaurados van a la carpeta plana MatchedMedia y los originales de fotos editadas a la carpeta plana EditedRaw. No se recrean las subcarpetas de Takeout. Los nombres repetidos reciben un n\u00famero (photo(1).jpg), sin sobrescribir archivos. Las parejas completadas pierden su JSON; los archivos con errores o sin pareja lo conservan.\n\nNo hay copia autom\u00e1tica ni deshacer. Un fallo de escritura puede dejar metadatos cambiados. Restauramos fechas, no viajamos en el tiempo.",
        "backup_continue": "Continuar y restaurar",
        "force": "Forzar", "force_tip": "Reintentar errores y archivos sin pareja con arreglos m\u00e1s arriesgados",
        "force_title": "\u00bfForzar los archivos pendientes?",
        "force_message": "Haz una copia de seguridad antes de continuar. GPMatcher reintenta archivos con errores o sin pareja con arreglos m\u00e1s arriesgados:\n\n\u2022 Corregir extensiones seg\u00fan el contenido real (por ejemplo, un PNG llamado .jpg).\n\u2022 Ignorar errores menores, reconstruir metadatos da\u00f1ados o, como \u00faltimo recurso, borrar metadatos existentes (c\u00e1mara, objetivo, etc.) antes de escribir los de Google Fotos.\n\u2022 Usar el \u00fanico archivo con el mismo nombre y otra extensi\u00f3n; descartar GPS o descripciones no v\u00e1lidos.\n\nLos reintentos de reparaci\u00f3n usan una copia temporal y solo sustituyen el original si tienen \u00e9xito. Las Live Photos solo reciben el reintento no destructivo.\n\nResultados: MatchedMedia/ForcedMatches; originales editados: EditedRaw/ForcedMatches. Los fallos conservan su JSON, cuentan como sin pareja y aparecen en el informe CSV. No se pueden forzar MKV, fechas ausentes ni parejas ambiguas.",
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
