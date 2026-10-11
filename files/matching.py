"""Pairs Google Takeout JSON sidecars with their media files."""
import os
import re
import unicodedata


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".heif", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".3gp", ".m4v", ".mkv"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
EDITED_SUFFIXES = ("editado", "editada", "edited", "modifié", "modifiée", "bearbeitet", "bewerkt", "modificato", "modificata", "redigerad")
HIDDEN_SUFFIXES = ("_PORTRAIT", "PORTRAIT", "_NFNR", "_MFNR")
EQUIVALENT_EXTENSIONS = ({".jpg", ".jpeg"}, {".tif", ".tiff"}, {".heic", ".heif"}, {".mp4", ".m4v", ".mov", ".3gp"})
HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}


def normalized_name(name):
    return unicodedata.normalize("NFC", name).casefold()


def detect_media_extension(filepath):
    """Return the extension matching the file content, or None when unknown."""
    with open(filepath, "rb") as stream:
        header = stream.read(64)
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    if header[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return ".mkv"
    if header[4:8] == b"ftyp":
        brands = header[8:min(len(header), max(int.from_bytes(header[:4], "big"), 12))]
        if b"avif" in brands:
            return None
        if header[8:12] in HEIF_BRANDS:
            return ".heic"
        if header[8:12] == b"qt  ":
            return ".mov"
        if header[8:11] == b"3gp":
            return ".3gp"
        return ".mp4"
    return None


def same_media_type(first, second):
    first, second = first.casefold(), second.casefold()
    return first == second or any(first in group and second in group for group in EQUIVALENT_EXTENSIONS)


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
