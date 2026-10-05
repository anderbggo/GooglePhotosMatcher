import sys
import csv
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import piexif
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "files"))

from auxFunctions import AmbiguousMatchError, EDITED_SUFFIXES, MediaMatcher, get_content_identifier, get_exiftool_path, searchMedia, set_image_metadata, set_photo_metadata, set_video_metadata, setWindowsTime
from main import mainProcess
from build import EXIFTOOL_VERSION, ROOT, build_command, prepare_exiftool


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def files(self, *names):
        for name in names:
            (self.root / name).touch()

    def match(self, title, moved=()):
        return searchMedia(str(self.root), title, moved, "", "editado")

    def test_exact_name_wins_over_numbered_duplicate(self):
        self.files("photo.jpg", "photo(1).jpg")
        self.assertEqual(self.match("photo.jpg"), (None, "photo.jpg"))

    def test_literal_filename_with_valid_special_characters(self):
        self.files("100% holiday.jpg", "100 holiday.jpg")
        self.assertEqual(self.match("100% holiday.jpg"), (None, "100% holiday.jpg"))

    def test_processed_file_is_not_reused(self):
        self.files("photo.jpg")
        self.assertEqual(self.match("photo.jpg", ["photo.jpg"]), (None, None))

    def test_ambiguous_prefix_is_not_guessed(self):
        self.files("holiday-one.jpg", "holiday-two.jpg")
        self.assertEqual(self.match("holiday.jpg"), (None, None))

    def test_unique_prefix_can_match_truncated_title(self):
        prefix = "holiday[1]-" + "x" * 36
        self.files(prefix + "-long-name.jpg")
        self.assertEqual(self.match(prefix + ".jpg"), (None, prefix + "-long-name.jpg"))

    def test_directory_is_not_a_media_file(self):
        (self.root / "photo.jpg").mkdir()
        self.assertEqual(self.match("photo.jpg"), (None, None))

    def test_short_prefix_does_not_match_an_unrelated_file(self):
        self.files("photo-other.jpg")
        self.assertEqual(self.match("photo.jpg"), (None, None))

    def test_numbered_sidecar_selects_the_correct_duplicate(self):
        self.files("photo.jpg", "photo(1).jpg", "photo(2).jpg")
        matcher = MediaMatcher(str(self.root))
        for sidecar in ("photo.jpg(2).json", "photo.jpg.supplemental-metadata(2).json", "photo(2).jpg.json"):
            with self.subTest(sidecar=sidecar):
                self.assertEqual(matcher.match("photo.jpg", sidecar), (None, "photo(2).jpg"))

    def test_missing_numbered_duplicate_does_not_reuse_original(self):
        self.files("photo.jpg")
        for sidecar in ("photo.jpg(2).json", "photo(2).jpg.json", "photo(2).jpg.supplemental-metadata.json"):
            with self.subTest(sidecar=sidecar):
                self.assertEqual(MediaMatcher(str(self.root)).match("photo.jpg", sidecar), (None, None))

    def test_truncated_duplicate_does_not_reuse_unnumbered_file(self):
        self.files("x" * 47 + ".jpg")
        self.assertEqual(MediaMatcher(str(self.root)).match("x" * 60 + ".jpg", "x" * 60 + ".jpg(2).json"), (None, None))

    def test_sidecar_name_resolves_a_truncated_title(self):
        self.files("complete-original-name.jpg")
        self.assertEqual(MediaMatcher(str(self.root)).match("complete", "complete-original-name.jpg.supplemental-metadata.json"), (None, "complete-original-name.jpg"))

    def test_case_insensitive_extensions(self):
        self.files("PHOTO.JPG")
        self.assertEqual(self.match("photo.jpg"), (None, "PHOTO.JPG"))

    def test_unicode_normalization(self):
        self.files("cafe\u0301.jpg")
        self.assertEqual(self.match("caf\u00e9.jpg"), (None, "cafe\u0301.jpg"))

    def test_camera_suffix(self):
        self.files("photo_PORTRAIT.jpg")
        self.assertEqual(self.match("photo.jpg"), (None, "photo_PORTRAIT.jpg"))

    def test_edited_original_pair(self):
        self.files("photo.jpg", "photo-edited.jpg")
        self.assertEqual(self.match("photo.jpg"), ("photo-edited.jpg", "photo.jpg"))

    def test_common_edited_suffixes_need_no_configuration(self):
        for index, suffix in enumerate(EDITED_SUFFIXES):
            with self.subTest(suffix=suffix):
                original = f"photo{index}.jpg"
                edited = f"photo{index}-{suffix}.jpg"
                self.files(original, edited)
                self.assertEqual(MediaMatcher(str(self.root)).match(original), (edited, original))

    def test_numbered_edited_pair(self):
        self.files("photo(2).jpg", "photo-edited(2).jpg")
        self.assertEqual(MediaMatcher(str(self.root)).match("photo.jpg", "photo.jpg(2).json"), ("photo-edited(2).jpg", "photo(2).jpg"))

    def test_ambiguous_truncation_reports_candidates(self):
        prefix = "x" * 47
        self.files(prefix + "-one.jpg", prefix + "-two.jpg")
        with self.assertRaises(AmbiguousMatchError) as result:
            MediaMatcher(str(self.root)).match(prefix + ".jpg")
        self.assertEqual(len(result.exception.candidates), 2)

    def test_truncated_media_name(self):
        self.files("x" * 47 + ".jpg")
        self.assertEqual(self.match("x" * 60 + ".jpg"), (None, "x" * 47 + ".jpg"))

    def test_windows_sanitized_filename(self):
        self.files("photo_name.jpg")
        self.assertEqual(self.match("photo:name.jpg"), (None, "photo_name.jpg"))

    def test_truncated_edited_filename_without_original(self):
        self.files("x" * 47 + "-edited.jpg")
        self.assertEqual(self.match("x" * 60 + ".jpg"), ("x" * 47 + "-edited.jpg", None))

    def test_camera_suffix_before_duplicate_number(self):
        self.files("photo_PORTRAIT(2).jpg")
        self.assertEqual(MediaMatcher(str(self.root)).match("photo.jpg", "photo.jpg(2).json"), (None, "photo_PORTRAIT(2).jpg"))

    def test_truncated_numbered_media_keeps_the_requested_number(self):
        self.files("x" * 47 + "(1).jpg", "x" * 47 + "(2).jpg")
        self.assertEqual(MediaMatcher(str(self.root)).match("x" * 60 + ".jpg", "x" * 60 + ".jpg(2).json"), (None, "x" * 47 + "(2).jpg"))


class ExifToolDiscoveryTests(unittest.TestCase):
    def test_bundled_exiftool_is_found_in_extracted_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "vendor" / "exiftool" / "exiftool.exe"
            path.parent.mkdir(parents=True)
            path.touch()
            path.chmod(0o755)
            with patch.object(sys, "_MEIPASS", folder, create=True), patch.object(sys, "frozen", True, create=True), patch("auxFunctions.platform.system", return_value="Windows"), patch("auxFunctions.shutil.which", return_value="other-exiftool"):
                self.assertEqual(get_exiftool_path(), str(path))

    def test_explicit_path_can_override_bundled_exiftool(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "custom-exiftool.exe"
            path.touch()
            path.chmod(0o755)
            with patch.object(sys, "_MEIPASS", folder, create=True):
                self.assertEqual(get_exiftool_path(str(path)), str(path))

    def test_path_installation_remains_a_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, "_MEIPASS", folder, create=True), patch("auxFunctions.shutil.which", return_value="installed-exiftool"):
                self.assertEqual(get_exiftool_path(), "installed-exiftool")


class BuildTests(unittest.TestCase):
    def test_archive_checksum_is_required_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "untrusted.zip"
            archive.write_bytes(b"untrusted archive")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                prepare_exiftool(archive, Path(folder) / "extracted")
            self.assertFalse((Path(folder) / "extracted").exists())

    def test_archive_cannot_escape_extraction_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("../outside.txt", "not allowed")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch("build.EXIFTOOL_SHA256", digest):
                with self.assertRaisesRegex(ValueError, "Unsafe path"):
                    prepare_exiftool(archive, Path(folder) / "extracted")
            self.assertFalse((Path(folder) / "outside.txt").exists())

    def test_complete_distribution_keeps_runtime_and_licenses(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "fixture.zip"
            prefix = f"exiftool-{EXIFTOOL_VERSION}_64/"
            required = ("exiftool(-k).exe", "exiftool_files/perl.exe", "exiftool_files/exiftool.pl", "exiftool_files/LICENSE", "exiftool_files/Licenses_Strawberry_Perl.zip", "README.txt")
            with zipfile.ZipFile(archive, "w") as stream:
                for filename in required:
                    stream.writestr(prefix + filename, "fixture")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch("build.EXIFTOOL_SHA256", digest):
                package = prepare_exiftool(archive, Path(folder) / "extracted")
            self.assertTrue((package / "exiftool.exe").is_file())
            self.assertTrue((package / "exiftool_files" / "LICENSE").is_file())
            self.assertTrue((package / "exiftool_files" / "perl.exe").is_file())

    def test_build_includes_entire_distribution_without_replacing_root_exe(self):
        package = Path("verified-exiftool")
        command = build_command(package)
        self.assertIn(f"{package};vendor/exiftool", command)
        self.assertEqual(command[command.index("--distpath") + 1], str(ROOT / "dist"))

    def test_bundle_check_does_not_accept_missing_internal_component(self):
        from window import _check_bundled_exiftool

        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "check.json"
            with patch("window.get_exiftool_path", return_value=None):
                self.assertFalse(_check_bundled_exiftool(report))
            self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["ok"])


class PreferenceTests(unittest.TestCase):
    def test_system_defaults_follow_dark_mode_and_spanish(self):
        from preferences import resolve_preferences

        with patch("preferences.system_theme", return_value="dark"), patch("preferences.system_language", return_value="es"):
            self.assertEqual(resolve_preferences({}), ("dark", "es"))

    def test_manual_choices_override_system_defaults(self):
        from preferences import resolve_preferences

        with patch("preferences.system_theme", return_value="dark"), patch("preferences.system_language", return_value="es"):
            self.assertEqual(resolve_preferences({"theme": "light", "language": "en"}), ("light", "en"))

    def test_preferences_are_persisted_and_corrupt_files_are_safe(self):
        from preferences import load_preferences, save_preferences

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preferences.json"
            self.assertEqual(load_preferences(path), {"theme": "system", "language": "system"})
            save_preferences({"theme": "dark", "language": "es"}, path)
            self.assertEqual(load_preferences(path), {"theme": "dark", "language": "es"})
            path.write_text("{", encoding="utf-8")
            self.assertEqual(load_preferences(path), {"theme": "system", "language": "system"})

    def test_translation_keys_match_and_filenames_are_preserved(self):
        from preferences import TEXT, localize_message

        self.assertEqual(set(TEXT["en"]), set(TEXT["es"]))
        self.assertEqual(localize_message("RESTORED: Photos/ERROR-photo.jpg", "es"), "RESTAURADO: Photos/ERROR-photo.jpg")
        self.assertEqual(localize_message("ERROR: photo.jpg | Missing photo timestamp", "es"), "ERROR: photo.jpg | Falta la fecha de la foto")
        self.assertEqual(localize_message("ERROR: Scanning: photo.jpg | Missing photo timestamp", "es"), "ERROR: Scanning: photo.jpg | Falta la fecha de la foto")

    def test_windows_defaults_read_application_theme_and_ui_language(self):
        from preferences import system_language, system_theme

        registry = SimpleNamespace(HKEY_CURRENT_USER=1, OpenKey=MagicMock(), QueryValueEx=MagicMock(return_value=(0, 0)))
        api = SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=MagicMock(return_value=0x0C0A)))
        with patch("preferences.platform.system", return_value="Windows"), patch.dict(sys.modules, {"winreg": registry}), patch("preferences.ctypes.windll", api, create=True):
            self.assertEqual(system_theme(), "dark")
            self.assertEqual(system_language(), "es")
            registry.QueryValueEx.return_value = (1, 0)
            api.kernel32.GetUserDefaultUILanguage.return_value = 0x0409
            self.assertEqual(system_theme(), "light")
            self.assertEqual(system_language(), "en")

    def test_spanish_number_format(self):
        from preferences import format_number

        self.assertEqual(format_number(1248, "es"), "1.248")
        self.assertEqual(format_number(1248, "en"), "1,248")

    def test_spanish_ui_localizes_status_logs_and_counters(self):
        import window as ui

        instance = MagicMock()
        instance.gpm_language = "es"
        widgets = {key: MagicMock() for key in ("-MATCHED-", "-EXISTING-", "-ERRORS-", "-UNMATCHED-", "-PROGRESS_LABEL-", "-LOG-", "Results", "Report", "Match", "Preview", "Cancel", "-IN2-", "-BROWSE_FOLDER-", "-PROGRESS_BAR-")}
        instance.__getitem__.side_effect = widgets.__getitem__
        summary = {"restored": 1248}
        instance.read.side_effect = [("-LOG-", {"-LOG-": "RESTORED: photo.jpg"}), ("-UPDATE_SUMMARY-", {"-UPDATE_SUMMARY-": summary}), ("-UPDATE_DONE-", {}), (ui.sg.WIN_CLOSED, {})]
        with patch("window.build_window", return_value=instance):
            ui.run_app()
        widgets["-MATCHED-"].update.assert_called_once_with("1.248")
        widgets["-LOG-"].print.assert_called_once_with("RESTAURADO: photo.jpg")
        widgets["-PROGRESS_LABEL-"].update.assert_called_with("Restauraci\u00f3n completada", text_color=ui.PALETTE["success"])

    def test_selector_events_save_canonical_choices(self):
        import window as ui

        instance = MagicMock()
        instance.gpm_language = "en"
        instance.gpm_preferences = {"theme": "system", "language": "system"}
        instance.read.side_effect = [("-THEME-", {"-THEME-": "Dark"}), ("-LANGUAGE-", {"-LANGUAGE-": "Espa\u00f1ol"}), (ui.sg.WIN_CLOSED, {})]

        def apply(window, values, persist=False):
            window.gpm_preferences = values

        with patch("window.build_window", return_value=instance), patch("window._apply_preferences", side_effect=apply) as preferences:
            ui.run_app()
        self.assertEqual(preferences.call_args_list, [
            call(instance, {"theme": "dark", "language": "system"}, persist=True),
            call(instance, {"theme": "dark", "language": "es"}, persist=True),
        ])


class V3InterfaceTests(unittest.TestCase):
    def test_palette_text_and_button_contrast(self):
        from preferences import PALETTES

        def luminance(color):
            channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for theme, palette in PALETTES.items():
            for foreground, background in (("text", "panel"), ("muted", "input_bg"), ("on_accent", "accent"), ("on_accent", "accent_soft"), ("support_text", "support_bg"), ("danger", "input_bg"), ("warning", "input_bg")):
                with self.subTest(theme=theme, foreground=foreground, background=background):
                    darker, lighter = sorted((luminance(palette[foreground]), luminance(palette[background])))
                    self.assertGreaterEqual((lighter + 0.05) / (darker + 0.05), 4.5)

    def test_summary_uses_grouped_numeric_counters(self):
        import window as ui

        instance = MagicMock()
        widgets = {key: MagicMock() for key in ("-MATCHED-", "-EXISTING-", "-ERRORS-", "-UNMATCHED-", "Results", "Report")}
        instance.__getitem__.side_effect = widgets.__getitem__
        instance.read.side_effect = [("-UPDATE_SUMMARY-", {"-UPDATE_SUMMARY-": {"restored": 1248, "already_restored": 36, "error": 2, "unmatched": 4}}), (ui.sg.WIN_CLOSED, {})]
        with patch("window.build_window", return_value=instance):
            ui.run_app()
        for key, value in (("-MATCHED-", "1,248"), ("-EXISTING-", "36"), ("-ERRORS-", "2"), ("-UNMATCHED-", "4")):
            widgets[key].update.assert_called_once_with(value)

    def test_live_counts_update_before_final_summary(self):
        import window as ui

        instance = MagicMock()
        instance.gpm_language = "es"
        widgets = {key: MagicMock() for key in ("-MATCHED-", "-EXISTING-", "-ERRORS-", "-UNMATCHED-")}
        instance.__getitem__.side_effect = widgets.__getitem__
        first = {"restored": 1, "error": 0, "unmatched": 2}
        second = {"restored": 1248, "error": 3, "unmatched": 1}
        instance.read.side_effect = [("-UPDATE_COUNTS-", {"-UPDATE_COUNTS-": first}), ("-UPDATE_COUNTS-", {"-UPDATE_COUNTS-": second}), (ui.sg.WIN_CLOSED, {})]
        with patch("window.build_window", return_value=instance):
            ui.run_app()
        self.assertEqual(widgets["-MATCHED-"].update.call_args_list, [call("1"), call("1.248")])
        self.assertEqual(widgets["-ERRORS-"].update.call_args_list, [call("0"), call("3")])
        self.assertEqual(widgets["-UNMATCHED-"].update.call_args_list, [call("2"), call("1")])
        self.assertEqual(instance.gpm_summary, second)

    def test_primary_button_has_a_clear_busy_state(self):
        from window import PALETTE, _set_busy

        instance = MagicMock()
        widgets = {key: MagicMock() for key in ("Preview", "Match", "-IN2-", "-BROWSE_FOLDER-", "Cancel")}
        instance.__getitem__.side_effect = widgets.__getitem__
        _set_busy(instance, True)
        widgets["Match"].update.assert_any_call(button_color=(PALETTE["muted"], PALETTE["panel_alt"]))
        _set_busy(instance, False)
        widgets["Match"].update.assert_any_call(button_color=(PALETTE["on_accent"], PALETTE["accent"]))

    def test_feedback_reinstallation_removes_previous_bindings(self):
        from window import _install_button_feedback

        instance = MagicMock()
        keys = ("Match", "Preview", "Cancel", "Results", "Report", "About", "Support", "-BROWSE_FOLDER-")
        widgets = {key: MagicMock() for key in keys}
        instance.__getitem__.side_effect = widgets.__getitem__
        for key, element in widgets.items():
            element.Widget.cget.return_value = "normal"
            element.Widget.bind.return_value = f"handler-{key}"
        _install_button_feedback(instance)
        _install_button_feedback(instance)
        self.assertEqual(len(instance.gpm_button_bindings), 48)
        for element in widgets.values():
            self.assertEqual(element.Widget.unbind.call_count, 6)


class AutomaticExifToolUITests(unittest.TestCase):
    def test_preview_and_restore_do_not_require_a_manual_exiftool_path(self):
        import window as ui

        with tempfile.TemporaryDirectory() as folder:
            for event in ("Preview", "Match"):
                with self.subTest(event=event):
                    instance = MagicMock()
                    instance.read.side_effect = [(event, {"-IN2-": folder}), (ui.sg.WIN_CLOSED, {})]
                    with patch("window.build_window", return_value=instance), patch("window._confirm_backup", return_value=True) as confirm, patch("window.threading.Thread") as worker:
                        worker.return_value.is_alive.return_value = False
                        ui.run_app()
                    if event == "Match":
                        confirm.assert_called_once_with(instance, Path(folder))
                    else:
                        confirm.assert_not_called()
                    self.assertEqual(worker.call_args.kwargs["args"], (folder, instance, ""))
                    self.assertEqual(worker.call_args.kwargs["kwargs"]["dry_run"], event == "Preview")
                    accessed = [arguments.args[0] for arguments in instance.__getitem__.call_args_list]
                    self.assertNotIn("-EXIFTOOL_PATH-", accessed)
                    self.assertNotIn("-BROWSE_EXIFTOOL-", accessed)
                    worker.return_value.start.assert_called_once()

    def test_cancelled_backup_warning_never_starts_processing(self):
        import window as ui

        with tempfile.TemporaryDirectory() as folder:
            instance = MagicMock()
            instance.read.side_effect = [("Match", {"-IN2-": folder}), (ui.sg.WIN_CLOSED, {})]
            with patch("window.build_window", return_value=instance), patch("window._confirm_backup", return_value=False), patch("window.threading.Thread") as worker:
                ui.run_app()
            worker.assert_not_called()

    def test_backup_dialog_requires_explicit_continue(self):
        import window as ui

        for event in ("Cancel", ui.sg.WIN_CLOSED, "Match"):
            with self.subTest(event=event):
                dialog = MagicMock()
                dialog.read.return_value = (event, {})
                with patch("window._build_backup_dialog", return_value=dialog):
                    self.assertEqual(ui._confirm_backup(MagicMock(), Path("folder")), event == "Match")
                dialog.close.assert_called_once()


class LinkButtonTests(unittest.TestCase):
    def test_about_and_support_open_requested_urls(self):
        import window as ui

        instance = MagicMock()
        instance.read.side_effect = [("About", {}), ("Support", {}), (ui.sg.WIN_CLOSED, {})]
        with patch("window.build_window", return_value=instance), patch("window.webbrowser.open_new_tab", return_value=True) as browser:
            ui.run_app()
        self.assertEqual(browser.call_args_list, [
            call("https://anderbggo.github.io/gpmatcher"),
            call("https://anderbggo.github.io/contribute"),
        ])
        instance.close.assert_called_once()

    def test_browser_failure_is_reported_without_closing_the_app(self):
        import window as ui

        instance = MagicMock()
        instance.read.side_effect = [("About", {}), (ui.sg.WIN_CLOSED, {})]
        with patch("window.build_window", return_value=instance), patch("window.webbrowser.open_new_tab", side_effect=OSError("Browser unavailable")):
            ui.run_app()
        instance.__getitem__.return_value.print.assert_called_once_with("Could not open browser: Browser unavailable")
        instance.close.assert_called_once()


class PersistentExifToolTests(unittest.TestCase):
    def test_batch_calls_use_the_session_and_close_it(self):
        from auxFunctions import _run_exiftool, exiftool_batch

        result = subprocess.CompletedProcess([], 0, b"metadata", b"")
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.ExifToolSession") as session, patch("auxFunctions.subprocess.run") as individual:
            session.return_value.execute.return_value = result
            with exiftool_batch():
                self.assertIs(_run_exiftool("one.png", ["-j"]), result)
                self.assertIs(_run_exiftool("two.png", ["-j"]), result)
            self.assertEqual(session.return_value.execute.call_count, 2)
            session.return_value.close.assert_called_once()
            individual.assert_not_called()

    def test_failed_status_is_not_treated_as_success(self):
        from auxFunctions import _run_exiftool, exiftool_batch

        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.ExifToolSession") as session:
            session.return_value.execute.return_value = subprocess.CompletedProcess([], 1, b"", b"write failed")
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                with exiftool_batch():
                    _run_exiftool("one.png", ["-overwrite_original"])
            session.return_value.close.assert_called_once()

    def test_multiline_metadata_uses_safe_individual_call(self):
        from auxFunctions import _run_exiftool, exiftool_batch

        result = subprocess.CompletedProcess([], 0, b"updated", b"")
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.ExifToolSession") as session, patch("auxFunctions.subprocess.run", return_value=result) as individual:
            with exiftool_batch():
                _run_exiftool("photo.png", ["-Description=First line\nSecond line"])
            session.return_value.execute.assert_not_called()
            self.assertIn("-Description=First line\nSecond line", individual.call_args.args[0])

    def test_session_is_lazy_for_jpeg_only_batches(self):
        from auxFunctions import exiftool_batch

        with patch("auxFunctions.subprocess.Popen") as start:
            with exiftool_batch():
                pass
            start.assert_not_called()

    def test_timeout_forces_session_shutdown(self):
        import queue
        from auxFunctions import ExifToolSession

        session = ExifToolSession(timeout=0.01)
        session.process = MagicMock()
        session.output = MagicMock()
        session.output.get.side_effect = queue.Empty
        with patch.object(session, "_start"), patch.object(session, "close") as close:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                session.execute("exiftool", "photo.png", ["-j"])
        close.assert_called_once_with(force=True)

    def test_unexpected_process_exit_fails_the_operation(self):
        from auxFunctions import ExifToolSession

        session = ExifToolSession()
        session.process = MagicMock()
        session.output = MagicMock()
        session.output.get.return_value = ("stdout", None)
        with patch.object(session, "_start"), patch.object(session, "close") as close:
            with self.assertRaisesRegex(RuntimeError, "ended before"):
                session.execute("exiftool", "photo.png", ["-j"])
        close.assert_called_once_with(force=True)


class MetadataTests(unittest.TestCase):
    def test_missing_exiftool_is_an_error(self):
        with patch("auxFunctions.get_exiftool_path", return_value=None):
            with self.assertRaises(FileNotFoundError):
                set_video_metadata("video.mov", 0, 0, 0, 1000000000)

    def test_exiftool_failure_is_an_error(self):
        result = SimpleNamespace(returncode=1, stderr=b"write denied", stdout=b"")
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "write denied"):
                set_video_metadata("video.mov", 0, 0, 0, 1000000000)

    def test_exiftool_timeout_is_an_error(self):
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.subprocess.run", side_effect=subprocess.TimeoutExpired("exiftool", 60)):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                set_video_metadata("video.mov", 0, 0, 0, 1000000000)

    def test_video_identifier_is_read_from_keys(self):
        result = SimpleNamespace(returncode=0, stderr=b"", stdout=json.dumps([{"Keys:ContentIdentifier": "live-id"}]).encode())
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.subprocess.run", return_value=result):
            self.assertEqual(get_content_identifier("video.mov"), "live-id")

    def test_conflicting_identifiers_are_rejected(self):
        result = SimpleNamespace(returncode=0, stderr=b"", stdout=json.dumps([{"Apple:ContentIdentifier": "one", "Keys:ContentIdentifier": "two"}]).encode())
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.subprocess.run", return_value=result):
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                get_content_identifier("video.mov")

    def test_exiftool_altitude_reference_is_written_as_a_number(self):
        result = SimpleNamespace(returncode=0, stderr=b"", stdout=b"1 image files updated")
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.subprocess.run", return_value=result) as runner:
            set_image_metadata("photo.png", 41, -3, -12, 1000000000)
            self.assertIn("-EXIF:GPSAltitudeRef#=1", runner.call_args.args[0])
            set_video_metadata("video.mov", 41, -3, -12, 1000000000)
            self.assertIn("-GPSAltitudeRef#=1", runner.call_args.args[0])
            self.assertIn("-Keys:GPSCoordinates=+41.000000000-003.000000000-12.000/", runner.call_args.args[0])

    def test_partial_exiftool_write_is_not_a_success(self):
        result = SimpleNamespace(returncode=0, stderr=b"Warning: Error converting value for Keys:GPSCoordinates", stdout=b"1 image files updated")
        with patch("auxFunctions.get_exiftool_path", return_value="exiftool"), patch("auxFunctions.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "could not write"):
                set_video_metadata("video.mov", 41, -3, -12, 1000000000)

    def test_jpeg_metadata_and_existing_tags_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "photo.jpg")
            Image.new("RGB", (16, 16), "red").save(path)
            exif = {"0th": {piexif.ImageIFD.Make: b"Existing camera"}, "Exif": {}, "GPS": {piexif.GPSIFD.GPSMapDatum: b"WGS-84"}}
            piexif.insert(piexif.dump(exif), path)
            set_photo_metadata(path, 0, -3.5, -12, 1000000000, "Description")
            written = piexif.load(path)
            self.assertEqual(written["0th"][piexif.ImageIFD.Make], b"Existing camera")
            self.assertEqual(written["GPS"][piexif.GPSIFD.GPSMapDatum], b"WGS-84")
            self.assertEqual(written["GPS"][piexif.GPSIFD.GPSLatitudeRef], b"N")
            self.assertEqual(written["GPS"][piexif.GPSIFD.GPSLongitudeRef], b"W")
            self.assertEqual(written["GPS"][piexif.GPSIFD.GPSAltitudeRef], 1)
            self.assertIn(piexif.ExifIFD.DateTimeOriginal, written["Exif"])
            original_time = written["Exif"][piexif.ExifIFD.DateTimeOriginal].decode()
            offset = written["Exif"][piexif.ExifIFD.OffsetTimeOriginal].decode()
            self.assertEqual(datetime.strptime(original_time + offset, "%Y:%m:%d %H:%M:%S%z").timestamp(), 1000000000)

    def test_file_timestamp_uses_the_original_epoch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "photo.jpg")
            Path(path).touch()
            with patch("auxFunctions.setctime", None):
                setWindowsTime(path, 1000000000.25)
            self.assertAlmostEqual(os.path.getmtime(path), 1000000000.25, places=3)


class RecordingWindow:
    def __init__(self):
        self.events = []

    def write_event_value(self, event, value):
        self.events.append((event, value))


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.window = RecordingWindow()

    def photo(self, name="photo.jpg"):
        path = self.root / name
        Image.new("RGB", (16, 16), "red").save(path)
        return path

    def sidecar(self, name="photo.jpg.json", title="photo.jpg", timestamp=1000000000, **fields):
        path = self.root / name
        path.write_text(json.dumps({"title": title, "photoTakenTime": {"timestamp": str(timestamp)}, **fields}), encoding="utf-8")
        return path

    def run_process(self, **options):
        return mainProcess(str(self.root), self.window, "", **options)

    def test_report_contains_only_errors_and_their_causes(self):
        from main import _report

        records = [
            {"json": "good.jpg.json", "media": "good.jpg", "status": "restored", "details": ""},
            {"json": "preview.jpg.json", "media": "preview.jpg", "status": "preview", "details": ""},
            {"json": "duplicate.json", "media": "good.jpg", "status": "skipped", "details": "Duplicate JSON"},
            {"json": "", "media": "orphan.jpg", "status": "unmatched", "details": "No JSON"},
            {"json": "bad.jpg.json", "media": "bad.jpg", "status": "error", "rule": "JSON title", "details": "Metadata write failed"},
        ]
        report = _report(self.root, records)
        with Path(report).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, ["json", "media", "details"])
            self.assertEqual(list(reader), [{"json": "bad.jpg.json", "media": "bad.jpg", "details": "Metadata write failed"}])

    def test_error_only_report_does_not_change_summary_counts(self):
        self.photo()
        self.sidecar()
        self.photo("orphan.jpg")
        (self.root / "broken.json").write_text("{", encoding="utf-8")
        summary = self.run_process()
        self.assertEqual(summary["restored"], 1)
        self.assertEqual(summary["error"], 1)
        self.assertEqual(summary["unmatched"], 1)
        with Path(summary["report"]).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["json"], "broken.json")
        self.assertTrue(rows[0]["details"])

    def test_successful_run_produces_report_without_error_rows(self):
        self.photo()
        self.sidecar()
        summary = self.run_process()
        with Path(summary["report"]).open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(list(csv.DictReader(stream)), [])
        self.assertEqual(summary["restored"], 1)

    def test_live_counts_arrive_between_restorations(self):
        self.photo()
        self.sidecar()
        self.photo("second.jpg")
        self.sidecar("second.jpg.json", "second.jpg")
        from main import _restore
        observed = []

        def restore(*arguments):
            snapshots = [value for event, value in self.window.events if event == "-UPDATE_COUNTS-"]
            observed.append(snapshots[-1].get("restored", 0))
            return _restore(*arguments)

        with patch("main._restore", side_effect=restore):
            summary = self.run_process()
        self.assertEqual(observed, [0, 1])
        snapshots = [value for event, value in self.window.events if event == "-UPDATE_COUNTS-"]
        self.assertEqual([value.get("restored", 0) for value in snapshots], [0, 1, 2])
        self.assertEqual(summary["restored"], 2)
        self.assertIsNot(snapshots[0], snapshots[1])

    def test_preview_counts_update_without_modifying_files(self):
        self.photo()
        self.sidecar()
        self.photo("orphan.jpg")
        summary = self.run_process(dry_run=True)
        snapshots = [value for event, value in self.window.events if event == "-UPDATE_COUNTS-"]
        self.assertEqual(snapshots[0]["unmatched"], 1)
        self.assertEqual(snapshots[-1]["preview"], 1)
        self.assertEqual(summary["unmatched"], snapshots[-1]["unmatched"])
        self.assertTrue((self.root / "photo.jpg").is_file())
        self.assertTrue((self.root / "photo.jpg.json").is_file())

    def test_live_error_counts_match_final_summary(self):
        self.photo()
        self.sidecar()
        (self.root / "bad.png").write_bytes(b"invalid PNG")
        self.sidecar("bad.png.json", "bad.png")
        from main import _write_metadata

        def write(path, *arguments, **options):
            if path.name == "bad.png":
                raise RuntimeError("Simulated metadata failure")
            return _write_metadata(path, *arguments, **options)

        with patch("main._write_metadata", side_effect=write):
            summary = self.run_process()
        snapshots = [value for event, value in self.window.events if event == "-UPDATE_COUNTS-"]
        self.assertEqual([value.get("error", 0) for value in snapshots], [0, 1, 1])
        for key in ("restored", "error", "unmatched"):
            self.assertEqual(snapshots[-1].get(key, 0), summary.get(key, 0))
        self.assertTrue((self.root / "bad.png.json").is_file())

    def test_cancellation_keeps_completed_live_counts(self):
        self.photo()
        self.sidecar()
        self.photo("second.jpg")
        self.sidecar("second.jpg.json", "second.jpg")
        cancelled = threading.Event()
        record = self.window.write_event_value

        def cancel_after_first(event, value):
            record(event, value)
            if event == "-UPDATE_COUNTS-" and value.get("restored") == 1:
                cancelled.set()

        self.window.write_event_value = cancel_after_first
        summary = self.run_process(cancel_event=cancelled)
        snapshots = [value for event, value in self.window.events if event == "-UPDATE_COUNTS-"]
        self.assertEqual(snapshots[-1]["restored"], 1)
        self.assertEqual(summary["restored"], 1)
        self.assertTrue(summary["cancelled"])
        self.assertTrue((self.root / "second.jpg.json").is_file())

    def test_live_unmatched_count_updates_for_confirmed_companion(self):
        self.photo()
        self.sidecar()
        (self.root / "photo.mov").write_bytes(b"live video")
        with patch("main.get_content_identifier", return_value="same-id"), patch("main.set_image_metadata"), patch("main.set_video_metadata"):
            summary = self.run_process()
        snapshots = [value for event, value in self.window.events if event == "-UPDATE_COUNTS-"]
        self.assertEqual(snapshots[0]["unmatched"], 1)
        self.assertEqual(snapshots[-1]["unmatched"], 0)
        self.assertEqual(summary.get("unmatched", 0), 0)

    def test_restoration_moves_original_and_deletes_matched_json(self):
        source = self.photo()
        sidecar = self.sidecar(description="Restored description")
        with patch("shutil.copy2", side_effect=AssertionError("Media must not be copied")):
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertFalse(source.exists())
        self.assertFalse(sidecar.exists())
        output = self.root / "MatchedMedia" / source.name
        self.assertEqual(piexif.load(str(output))["0th"][piexif.ImageIFD.ImageDescription], b"Restored description")
        self.assertFalse((output.parent / sidecar.name).exists())
        self.assertTrue(Path(summary["report"]).is_file())

    def test_numbered_jsons_restore_distinct_photos(self):
        self.photo()
        self.photo("photo(2).jpg")
        self.sidecar(description="First")
        self.sidecar("photo.jpg(2).json", description="Second")
        summary = self.run_process()
        self.assertEqual(summary.get("restored"), 2)
        for name, expected in (("photo.jpg", b"First"), ("photo(2).jpg", b"Second")):
            self.assertEqual(piexif.load(str(self.root / "MatchedMedia" / name))["0th"][piexif.ImageIFD.ImageDescription], expected)

    def test_existing_different_output_is_never_overwritten(self):
        source = self.photo()
        self.sidecar(description="New")
        output = self.root / "MatchedMedia" / source.name
        output.parent.mkdir()
        output.write_bytes(b"existing result")
        summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertEqual(output.read_bytes(), b"existing result")
        self.assertTrue(source.is_file())
        self.assertTrue((self.root / "photo.jpg.json").is_file())
        self.assertFalse(list(output.parent.glob(".gpm-*")))

    def test_repeated_run_does_not_process_moved_media_again(self):
        self.photo()
        self.sidecar()
        self.assertEqual(self.run_process().get("restored"), 1)
        self.assertNotIn("restored", self.run_process())
        self.assertEqual(len(list((self.root / "MatchedMedia").glob("*.jpg"))), 1)

    def test_metadata_failure_keeps_sources_and_removes_temporary_files(self):
        source = self.photo()
        sidecar = self.sidecar()
        with patch("main._write_metadata", side_effect=RuntimeError("simulated failure")):
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertTrue(source.is_file())
        self.assertTrue(sidecar.is_file())
        self.assertFalse((self.root / "MatchedMedia" / source.name).exists())
        self.assertFalse(list((self.root / "MatchedMedia").glob(".gpm-*")))

    def test_missing_exiftool_does_not_report_video_success(self):
        (self.root / "video.mov").write_bytes(b"video")
        self.sidecar("video.mov.json", "video.mov")
        with patch("auxFunctions.get_exiftool_path", return_value=None):
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertNotIn("restored", summary)
        self.assertTrue((self.root / "video.mov.json").is_file())

    def test_preview_does_not_write_media(self):
        self.photo()
        self.sidecar()
        summary = self.run_process(dry_run=True)
        self.assertEqual(summary.get("preview"), 1)
        self.assertFalse(list((self.root / "MatchedMedia").glob("*.jpg")))

    def test_cancelled_run_keeps_sources(self):
        self.photo()
        self.sidecar()
        cancelled = threading.Event()
        cancelled.set()
        summary = self.run_process(cancel_event=cancelled)
        self.assertTrue(summary.get("cancelled"))
        self.assertTrue((self.root / "photo.jpg").is_file())
        self.assertNotIn("restored", summary)

    def test_conflicting_sidecars_do_not_overwrite_each_other(self):
        self.photo()
        self.sidecar()
        self.sidecar("photo.jpg.supplemental-metadata.json", timestamp=1500000000)
        summary = self.run_process()
        self.assertEqual(summary.get("error"), 2)
        self.assertFalse((self.root / "MatchedMedia" / "photo.jpg").exists())

    def test_unrelated_same_stem_video_is_not_modified(self):
        self.photo()
        self.sidecar()
        (self.root / "photo.mov").write_bytes(b"unrelated video")
        with patch("main.get_content_identifier", return_value=None), patch("main.set_video_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertEqual(summary.get("unmatched"), 1)
        writer.assert_not_called()
        self.assertFalse((self.root / "MatchedMedia" / "photo.mov").exists())

    def test_confirmed_live_photo_without_video_json_is_restored(self):
        self.photo()
        self.sidecar()
        (self.root / "photo.mov").write_bytes(b"live video")
        with patch("main.get_content_identifier", return_value="same-id"), patch("main.set_image_metadata"), patch("main.set_video_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        writer.assert_called_once()
        self.assertTrue((self.root / "MatchedMedia" / "photo.mov").is_file())
        self.assertFalse((self.root / "photo.mov").exists())
        self.assertFalse((self.root / "photo.jpg.json").exists())

    def test_failed_live_photo_rolls_back_the_whole_output_group(self):
        self.photo()
        self.sidecar()
        (self.root / "photo.mov").write_bytes(b"live video")
        with patch("main.get_content_identifier", return_value="same-id"), patch("main.set_image_metadata"), patch("main.set_video_metadata", side_effect=RuntimeError("video failed")):
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertFalse(list((self.root / "MatchedMedia").glob("*.jpg")))
        self.assertFalse(list((self.root / "MatchedMedia").glob("*.mov")))
        self.assertTrue((self.root / "photo.jpg.json").is_file())
        self.assertTrue((self.root / "photo.jpg").is_file())
        self.assertTrue((self.root / "photo.mov").is_file())

    def test_video_with_own_json_keeps_its_metadata(self):
        self.photo()
        self.sidecar()
        (self.root / "photo.mov").write_bytes(b"video")
        self.sidecar("photo.mov.json", "photo.mov", timestamp=1500000000, description="Video description")
        with patch("main.get_content_identifier") as identifier, patch("main.set_video_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 2)
        identifier.assert_not_called()
        self.assertEqual(writer.call_args.args[4:6], (1500000000, "Video description"))

    def test_edited_and_original_media_use_separate_output_folders(self):
        self.photo()
        self.photo("photo-edited.jpg")
        self.sidecar()
        summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertTrue((self.root / "MatchedMedia" / "photo-edited.jpg").is_file())
        original_output = self.root / "EditedRaw" / "photo.jpg"
        edited_output = self.root / "MatchedMedia" / "photo-edited.jpg"
        self.assertTrue(original_output.is_file())
        for path in (original_output, edited_output):
            self.assertIn(piexif.ExifIFD.DateTimeOriginal, piexif.load(str(path))["Exif"])
        self.assertFalse((self.root / "photo.jpg").exists())
        self.assertFalse((self.root / "photo-edited.jpg").exists())
        self.assertFalse((self.root / "photo.jpg.json").exists())
        self.assertFalse((self.root / "MatchedMedia" / "photo.jpg").exists())

    def test_shared_png_json_restores_original_and_edited_before_moving(self):
        self.photo("example.png")
        self.photo("example-edited.png")
        self.sidecar("example.png.json", "example.png", description="Shared metadata")
        with patch("main.set_image_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertEqual({Path(arguments.args[0]).name for arguments in writer.call_args_list}, {"example.png", "example-edited.png"})
        for arguments in writer.call_args_list:
            self.assertEqual(arguments.args[4:6], (1000000000, "Shared metadata"))
        self.assertTrue((self.root / "EditedRaw" / "example.png").is_file())
        self.assertTrue((self.root / "MatchedMedia" / "example-edited.png").is_file())
        self.assertFalse((self.root / "example.png.json").exists())

    def test_edited_raw_conflict_keeps_both_sources_and_json(self):
        original = self.photo()
        edited = self.photo("photo-edited.jpg")
        sidecar = self.sidecar()
        target = self.root / "EditedRaw" / original.name
        target.parent.mkdir()
        target.write_bytes(b"previous original")
        with patch("main._write_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        writer.assert_not_called()
        self.assertTrue(original.is_file())
        self.assertTrue(edited.is_file())
        self.assertTrue(sidecar.is_file())
        self.assertEqual(target.read_bytes(), b"previous original")

    def test_malformed_and_non_media_jsons_are_reported(self):
        (self.root / "broken.json").write_text("{", encoding="utf-8")
        (self.root / "album.json").write_text('{"title": "Album"}', encoding="utf-8")
        summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertEqual(summary.get("skipped"), 1)

    def test_external_drive_without_hard_links_is_supported(self):
        self.photo()
        self.sidecar()
        with patch("main.os.link", side_effect=OSError("hard links not supported")):
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertTrue((self.root / "MatchedMedia" / "photo.jpg").is_file())
        self.assertAlmostEqual((self.root / "MatchedMedia" / "photo.jpg").stat().st_mtime, 1000000000)

    def test_failed_group_move_restores_original_locations(self):
        self.photo()
        self.photo("photo-edited.jpg")
        self.sidecar()
        from main import _move_no_replace
        calls = []

        def fail_second_move(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise FileExistsError("concurrent output")
            return _move_no_replace(source, destination)

        with patch("main._move_no_replace", side_effect=fail_second_move):
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertFalse((self.root / "MatchedMedia" / "photo.jpg").exists())
        self.assertFalse((self.root / "MatchedMedia" / "photo-edited.jpg").exists())
        self.assertTrue((self.root / "photo.jpg").is_file())
        self.assertTrue((self.root / "photo-edited.jpg").is_file())
        self.assertTrue((self.root / "photo.jpg.json").is_file())

    def test_edited_photo_with_own_json_uses_its_own_metadata(self):
        self.photo()
        self.photo("photo-edited.jpg")
        self.sidecar(description="Original")
        self.sidecar("photo-edited.jpg.json", "photo-edited.jpg", description="Edited")
        summary = self.run_process()
        self.assertEqual(summary.get("restored"), 2)
        for folder, name, expected in (("EditedRaw", "photo.jpg", b"Original"), ("MatchedMedia", "photo-edited.jpg", b"Edited")):
            self.assertEqual(piexif.load(str(self.root / folder / name))["0th"][piexif.ImageIFD.ImageDescription], expected)

    def test_invalid_video_sidecar_is_not_replaced_with_photo_metadata(self):
        self.photo()
        self.sidecar()
        (self.root / "photo.mov").write_bytes(b"video")
        (self.root / "photo.mov.json").write_text("{", encoding="utf-8")
        with patch("main.get_content_identifier", return_value="same-id"), patch("main.set_video_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertEqual(summary.get("error"), 1)
        writer.assert_not_called()

    def test_identical_sidecars_are_processed_only_once(self):
        self.photo()
        self.sidecar()
        self.sidecar("photo.jpg.supplemental-metadata.json")
        summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertEqual(summary.get("skipped"), 1)
        self.assertFalse((self.root / "photo.jpg.json").exists())
        self.assertFalse((self.root / "photo.jpg.supplemental-metadata.json").exists())

    def test_json_deletion_failure_returns_media_to_original_location(self):
        self.photo()
        first = self.sidecar()
        second = self.sidecar("photo.jpg.supplemental-metadata.json")
        original_json = first.read_bytes()
        unlink = Path.unlink

        def refuse_second_sidecar(path, *args, **kwargs):
            if path == second:
                raise PermissionError("JSON is locked")
            return unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", refuse_second_sidecar):
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertTrue((self.root / "photo.jpg").is_file())
        self.assertEqual(first.read_bytes(), original_json)
        self.assertTrue(second.is_file())
        self.assertFalse((self.root / "MatchedMedia" / "photo.jpg").exists())

    def test_existing_destination_is_checked_before_original_metadata_changes(self):
        source = self.photo()
        self.sidecar(description="New description")
        original = source.read_bytes()
        output = self.root / "MatchedMedia" / "photo.jpg"
        output.parent.mkdir()
        output.write_bytes(b"existing result")
        with patch("main._write_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        writer.assert_not_called()
        self.assertEqual(source.read_bytes(), original)

    def test_json_bom_uppercase_suffix_and_exif_gps_fallback(self):
        self.photo()
        path = self.root / "photo.jpg.JSON"
        path.write_text(json.dumps({"title": "photo.jpg", "photoTakenTime": {}, "photoLastModifiedTime": {"timestamp": "1000000000"}, "geoData": {"latitude": 0, "longitude": 0}, "geoDataExif": {"latitude": 41, "longitude": -3}}), encoding="utf-8-sig")
        summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertIn(piexif.GPSIFD.GPSLatitude, piexif.load(str(self.root / "MatchedMedia" / "photo.jpg"))["GPS"])

    def test_invalid_coordinates_are_not_silently_ignored(self):
        self.photo()
        self.sidecar(geoData={"latitude": 95, "longitude": 0})
        summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertFalse((self.root / "MatchedMedia" / "photo.jpg").exists())

    def test_missing_timestamp_is_not_replaced_with_epoch_zero(self):
        self.photo()
        path = self.sidecar()
        path.write_text('{"title": "photo.jpg", "photoTakenTime": {}}', encoding="utf-8")
        summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertFalse((self.root / "MatchedMedia" / "photo.jpg").exists())

    def test_ambiguous_matches_are_listed_in_report(self):
        prefix = "x" * 47
        self.photo(prefix + "-one.jpg")
        self.photo(prefix + "-two.jpg")
        self.sidecar(prefix + ".jpg.json", prefix + ".jpg")
        summary = self.run_process()
        with Path(summary["report"]).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(summary.get("error"), 1)
        self.assertTrue(any("Ambiguous match" in row["details"] for row in rows))
        self.assertEqual(summary.get("unmatched"), 2)

    def test_subfolders_are_preserved_and_outputs_are_not_scanned(self):
        folder = self.root / "Photos from 2020"
        folder.mkdir()
        self.photo().rename(folder / "photo.jpg")
        self.sidecar().rename(folder / "photo.jpg.json")
        existing = folder / "MatchedMedia"
        existing.mkdir()
        (existing / "broken.json").write_text("{", encoding="utf-8")
        summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        self.assertNotIn("error", summary)
        self.assertTrue((self.root / "MatchedMedia" / folder.name / "photo.jpg").is_file())

    def test_png_uses_exiftool_instead_of_piexif(self):
        self.photo("photo.png")
        self.sidecar("photo.png.json", "photo.png")
        with patch("main.set_image_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("restored"), 1)
        writer.assert_called_once()

    def test_mkv_is_reported_as_unsupported_without_false_success(self):
        (self.root / "video.mkv").write_bytes(b"video")
        self.sidecar("video.mkv.json", "video.mkv")
        with patch("main.set_video_metadata") as writer:
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        writer.assert_not_called()
        self.assertFalse((self.root / "MatchedMedia" / "video.mkv").exists())

    def test_live_photo_identifier_loss_is_not_reported_as_success(self):
        self.photo()
        self.sidecar()
        (self.root / "photo.mov").write_bytes(b"live video")
        with patch("main.get_content_identifier", side_effect=["same-id", "same-id", None]), patch("main.set_image_metadata"):
            summary = self.run_process()
        self.assertEqual(summary.get("error"), 1)
        self.assertFalse((self.root / "MatchedMedia" / "photo.jpg").exists())
        self.assertTrue((self.root / "photo.jpg.json").is_file())


if __name__ == "__main__":
    unittest.main()