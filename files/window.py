import ctypes
import io
import json
import os
import platform
import subprocess
import sys
import threading
import tkinter
import tempfile
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import ttk

import PySimpleGUI as sg
from PIL import Image

from auxFunctions import _run_exiftool, exiftool_batch, get_exiftool_path, resource_path, set_image_metadata
from main import mainProcess
from preferences import (
    LANGUAGE_OPTIONS, LIGHT_PALETTE, PALETTES, THEME_OPTIONS, format_number,
    load_preferences, localize_message, resolve_preferences, save_preferences,
    text, validate_preferences,
)


if sys.version_info >= (3, 14):
    def _trace_compatibility(self, mode, callback):
        trace_modes = {"r": "read", "w": "write", "u": "unset"}
        return self.trace_add(trace_modes.get(mode, mode), callback)

    tkinter.Variable.trace = _trace_compatibility
    tkinter.Variable.trace_variable = _trace_compatibility

PALETTE = LIGHT_PALETTE
FONT = "Segoe UI" if platform.system() == "Windows" else "Helvetica"
DISPLAY_FONT = "Bahnschrift" if platform.system() == "Windows" else "Avenir Next"
APP_VERSION = "3.0"
PROJECT_LINKS = {
    "About": "https://anderbggo.github.io/gpmatcher",
    "Support": "https://anderbggo.github.io/contribute",
}


def load_logo_data(path, size=(48, 48)):
    with Image.open(path) as logo_image:
        logo_image = logo_image.convert("RGBA")
        logo_image.thumbnail(size)
        buffer = io.BytesIO()
        logo_image.save(buffer, format="PNG")
        return buffer.getvalue()


def panel(content, pad=(24, 12), expand_y=False, background_color=None):
    return sg.Column(
        content,
        background_color=background_color or PALETTE["panel"],
        pad=pad,
        expand_x=True,
        expand_y=expand_y,
        element_justification="left",
        vertical_alignment="top",
    )


def counter_column(label, key, color, palette=None):
    palette = palette or PALETTE
    return sg.Column([
        [sg.Text("0", key=key, size=(10, 1), font=(DISPLAY_FONT, 20), text_color=color, background_color=palette["input_bg"])],
        [sg.Text(label, key=f"{key}label", font=(FONT, 10), text_color=palette["muted"], background_color=palette["input_bg"], pad=((0, 0), (4, 0)))],
    ], background_color=palette["input_bg"], expand_x=True, pad=((0, 12), (0, 0)))


def _window_palette(window):
    palette = getattr(window, "gpm_palette", None)
    return palette if isinstance(palette, dict) else PALETTE


def _window_language(window):
    language = getattr(window, "gpm_language", None)
    return language if isinstance(language, str) and language in ("en", "es") else "en"


def _choice_labels(language, options):
    return ["English" if option == "en" else "Espa\u00f1ol" if option == "es" else text(language, option) for option in options]


def _install_button_feedback(window, keys=("Match", "Preview", "Cancel", "Results", "Report", "About", "Support", "-BROWSE_FOLDER-")):
    previous = getattr(window, "gpm_button_bindings", None)
    if isinstance(previous, list):
        for widget, sequence, binding in previous:
            try:
                widget.unbind(sequence, binding)
            except tkinter.TclError:
                pass
    renderers = {}
    bindings = []
    for key in keys:
        widget = window[key].Widget
        state = {"hover": False, "pressed": False, "focus": False}

        def render(widget=widget, key=key, state=state):
            palette = _window_palette(window)
            if str(widget.cget("state")) == "disabled":
                state.update(hover=False, pressed=False, focus=False)
                foreground, background = palette["muted"], palette["panel_alt"]
                border, cursor = background, "arrow"
            else:
                hover_background = palette.get("hover", "#DCECE7")
                if key == "Match":
                    foreground = palette["on_accent"]
                    background = palette["accent_soft"] if state["pressed"] else palette["accent"]
                    if state["hover"] and not state["pressed"]:
                        background = palette.get("accent_hover", "#09654F")
                elif key == "Support":
                    foreground, background = (palette["on_accent"], palette["support_text"]) if state["hover"] or state["pressed"] else (palette["support_text"], palette["support_bg"])
                elif key == "Cancel":
                    foreground, background = (palette["danger"], palette["support_bg"]) if state["hover"] else (palette["muted"], palette["panel"])
                elif key == "About":
                    foreground, background = (palette["accent"], hover_background) if state["hover"] else (palette["muted"], palette["panel"])
                else:
                    foreground, background = (palette["accent"], hover_background) if state["hover"] else (palette["text"], palette["panel_alt"])
                    if state["pressed"]:
                        background = palette["line"]
                border = palette["accent"] if state["focus"] else background
                cursor = "hand2"
            widget.configure(
                foreground=foreground, background=background, activeforeground=foreground,
                activebackground=background, disabledforeground=palette["muted"],
                highlightbackground=border, highlightcolor=palette["accent"], highlightthickness=2,
                relief="flat", overrelief="flat", borderwidth=0, cursor=cursor, takefocus=True,
            )

        def change(name, value, state=state, render=render):
            state[name] = value
            if name == "hover" and not value:
                state["pressed"] = False
            render()

        for sequence, name, value in (("<Enter>", "hover", True), ("<Leave>", "hover", False), ("<ButtonPress-1>", "pressed", True), ("<ButtonRelease-1>", "pressed", False), ("<FocusIn>", "focus", True), ("<FocusOut>", "focus", False)):
            binding = widget.bind(sequence, lambda event, name=name, value=value, change=change: change(name, value), add="+")
            bindings.append((widget, sequence, binding))
        renderers[key] = render
        render()
    window.gpm_button_feedback = renderers
    window.gpm_button_bindings = bindings


def _refresh_button_feedback(window):
    renderers = getattr(window, "gpm_button_feedback", None)
    if isinstance(renderers, dict):
        for render in renderers.values():
            render()


def _capture_color_roles(window, palette):
    roles = []
    pending = [window.TKroot]
    while pending:
        widget = pending.pop()
        pending.extend(widget.winfo_children())
        if isinstance(widget, ttk.Widget):
            continue
        for option in ("background", "foreground", "insertbackground", "highlightbackground", "highlightcolor", "selectbackground", "selectforeground", "disabledbackground", "disabledforeground", "readonlybackground"):
            try:
                current = str(widget.cget(option)).casefold()
            except tkinter.TclError:
                continue
            role = next((name for name, color in palette.items() if color.casefold() == current), None)
            if role:
                roles.append((widget, option, role))
    window.gpm_color_roles = roles


def _style_native_controls(window):
    palette = _window_palette(window)
    style = ttk.Style(window.TKroot)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    style.configure("Gpm.TCombobox", fieldbackground=palette["input_bg"], background=palette["panel_alt"], foreground=palette["text"], arrowcolor=palette["text"], bordercolor=palette["line"], lightcolor=palette["line"], darkcolor=palette["line"], padding=(6, 3))
    style.map("Gpm.TCombobox", fieldbackground=[("readonly", palette["input_bg"])], foreground=[("disabled", palette["muted"])], background=[("active", palette["hover"])], bordercolor=[("focus", palette["accent"])])
    for key in ("-THEME-", "-LANGUAGE-"):
        window[key].Widget.configure(style="Gpm.TCombobox")
    style.configure("Gpm.Horizontal.TProgressbar", background=palette["accent"], troughcolor=palette["panel_alt"], bordercolor=palette["panel_alt"], lightcolor=palette["accent"], darkcolor=palette["accent"])
    window["-PROGRESS_BAR-"].Widget.configure(style="Gpm.Horizontal.TProgressbar")
    style.configure("Gpm.Horizontal.TSeparator", background=palette["line"])
    for key in ("-TOP_LINE-", "-BOTTOM_LINE-"):
        window[key].Widget.configure(style="Gpm.Horizontal.TSeparator")
    style.configure("Gpm.Vertical.TScrollbar", background=palette["panel_alt"], troughcolor=palette["input_bg"], bordercolor=palette["input_bg"], lightcolor=palette["panel_alt"], darkcolor=palette["panel_alt"], arrowcolor=palette["muted"], arrowsize=11)
    style.map("Gpm.Vertical.TScrollbar", background=[("pressed", palette["accent"]), ("active", palette["line"])], arrowcolor=[("active", palette["text"])])
    log = window["-LOG-"]
    if isinstance(log.vsb, tkinter.Scrollbar):
        previous = log.vsb
        layout = previous.pack_info()
        previous.pack_forget()
        log.vsb = ttk.Scrollbar(previous.master, orient="vertical", command=log.Widget.yview, style="Gpm.Vertical.TScrollbar")
        log.vsb.pack(**layout, before=log.Widget)
        log.Widget.configure(yscrollcommand=log.vsb.set)
        previous.destroy()
    else:
        log.vsb.configure(style="Gpm.Vertical.TScrollbar")
    for option, value in (("background", palette["panel"]), ("foreground", palette["text"]), ("selectBackground", palette["accent"]), ("selectForeground", palette["on_accent"])):
        window.TKroot.option_add(f"*TCombobox*Listbox.{option}", value)
    window["-IN2-"].Widget.configure(relief="flat", highlightthickness=1, highlightbackground=palette["line"], highlightcolor=palette["accent"], insertbackground=palette["text"], background=palette["input_bg"], foreground=palette["text"], disabledbackground=palette["panel_alt"], disabledforeground=palette["muted"], readonlybackground=palette["input_bg"])


def _log_color(message, palette):
    if message.startswith("ERROR"):
        return palette["danger"]
    if message.startswith("RESTORED"):
        return palette["success"]
    return palette["text"]


def _append_log(window, message):
    history = getattr(window, "gpm_log", None)
    if isinstance(history, deque):
        history.append(message)
        palette = _window_palette(window)
        window["-LOG-"].print(localize_message(message, _window_language(window)), text_color=_log_color(message, palette), background_color=palette["input_bg"])
    else:
        window["-LOG-"].print(localize_message(message, _window_language(window)))


def _set_status(window, key=None, message=None, color="muted", progress=None, filename=None):
    window.gpm_status = {"key": key, "message": message, "color": color, "progress": progress, "filename": filename}
    language = _window_language(window)
    if progress is not None:
        progress_text = f"{progress:g}"
        if language == "es":
            progress_text = progress_text.replace(".", ",")
        name = localize_message(filename or "", language)
        display_name = name if len(name) <= 80 else name[:77] + "..."
        value = f"{progress_text}% | {display_name}"
        window["-PROGRESS_LABEL-"].set_tooltip(name)
    else:
        value = text(language, key) if key else localize_message(message or "", language)
    window["-PROGRESS_LABEL-"].update(value, text_color=_window_palette(window)[color])


def _update_counters(window, summary):
    language = _window_language(window)
    for key, value in (("-MATCHED-", summary.get("restored", 0) + summary.get("preview", 0)), ("-EXISTING-", summary.get("already_restored", 0)), ("-ERRORS-", summary.get("error", 0)), ("-UNMATCHED-", summary.get("unmatched", 0))):
        window[key].update(format_number(value, language))


def _apply_preferences(window, values, persist=False):
    values = validate_preferences(values)
    theme, language = resolve_preferences(values)
    window.gpm_preferences, window.gpm_language = values, language
    window.gpm_palette = PALETTES[theme]
    for widget, option, role in window.gpm_color_roles:
        try:
            widget.configure(**{option: window.gpm_palette[role]})
        except tkinter.TclError:
            pass
    _style_native_controls(window)
    labels = {
        "-FOLDER_LABEL-": "folder", "-THEME_LABEL-": "theme", "-LANGUAGE_LABEL-": "language",
        "-ACTIVITY_LABEL-": "activity", "-BROWSE_FOLDER-": "browse", "Match": "match", "Preview": "preview",
        "Cancel": "cancel", "Results": "results", "Report": "report", "About": "about", "Support": "support",
        "-MATCHED-label": "matched", "-EXISTING-label": "existing", "-ERRORS-label": "errors", "-UNMATCHED-label": "unmatched",
    }
    for key, translation in labels.items():
        window[key].update(text(language, translation))
    for key, options, selected in (("-THEME-", THEME_OPTIONS, values["theme"]), ("-LANGUAGE-", LANGUAGE_OPTIONS, values["language"])):
        labels = _choice_labels(language, options)
        window[key].update(values=labels, value=labels[options.index(selected)])
    for key, translation in (("About", "about_tip"), ("Support", "support_tip"), ("-THEME-", "theme_tip"), ("-LANGUAGE-", "language_tip")):
        window[key].set_tooltip(text(language, translation))
    _install_button_feedback(window)
    _update_counters(window, window.gpm_summary)
    status = window.gpm_status
    _set_status(window, **status)
    window["-LOG-"].update("")
    palette = _window_palette(window)
    for message in window.gpm_log:
        window["-LOG-"].print(localize_message(message, language), text_color=_log_color(message, palette), background_color=palette["input_bg"])
    if persist:
        try:
            save_preferences(values)
        except OSError as error:
            _append_log(window, text("en", "preferences_failed", detail=error))


def build_window(preferences=None):
    preferences = validate_preferences(load_preferences() if preferences is None else preferences)
    theme, language = resolve_preferences(preferences)
    palette = PALETTES[theme]
    if platform.system() == "Windows":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    sg.theme_add_new("GPMatcherV3", {
        "BACKGROUND": palette["bg"], "TEXT": palette["text"],
        "INPUT": palette["input_bg"], "TEXT_INPUT": palette["text"],
        "SCROLL": palette["line"], "BUTTON": (palette["on_accent"], palette["accent"]),
        "PROGRESS": (palette["accent"], palette["panel_alt"]),
        "BORDER": 0, "SLIDER_DEPTH": 0, "PROGRESS_DEPTH": 0,
    })
    sg.theme("GPMatcherV3")
    sg.set_options(font=(FONT, 11), element_padding=(0, 0), margins=(0, 0), background_color=palette["bg"])
    icon_path = resource_path("assets/photo.ico")
    if not os.path.isfile(icon_path):
        icon_path = resource_path("photo.ico")

    header = panel([[
        sg.Image(data=load_logo_data(icon_path), background_color=palette["panel"], pad=((0, 16), (0, 0))),
        sg.Text("Google Photos Matcher", font=(DISPLAY_FONT, 21), background_color=palette["panel"]),
        sg.Push(background_color=palette["panel"]),
        sg.Text(f"v{APP_VERSION}", font=(FONT, 11, "bold"), text_color=palette["accent"], background_color=palette["panel"]),
    ]], pad=(28, 18), background_color=palette["panel"])
    appearance = panel([[
        sg.Text(text(language, "theme"), key="-THEME_LABEL-", background_color=palette["panel"], text_color=palette["muted"], pad=((0, 10), (0, 0))),
        sg.Combo(_choice_labels(language, THEME_OPTIONS), default_value=_choice_labels(language, THEME_OPTIONS)[THEME_OPTIONS.index(preferences["theme"])], key="-THEME-", readonly=True, enable_events=True, size=(12, 1), font=(FONT, 10), pad=((0, 24), (0, 0))),
        sg.Text(text(language, "language"), key="-LANGUAGE_LABEL-", background_color=palette["panel"], text_color=palette["muted"], pad=((0, 10), (0, 0))),
        sg.Combo(_choice_labels(language, LANGUAGE_OPTIONS), default_value=_choice_labels(language, LANGUAGE_OPTIONS)[LANGUAGE_OPTIONS.index(preferences["language"])], key="-LANGUAGE-", readonly=True, enable_events=True, size=(14, 1), font=(FONT, 10)),
    ]], pad=(28, 8), background_color=palette["panel"])
    settings = panel([
        [sg.Text(text(language, "folder"), key="-FOLDER_LABEL-", font=(FONT, 11, "bold"), background_color=palette["panel"], pad=((0, 0), (0, 10)))],
        [sg.Input(key="-IN2-", size=(46, 1), expand_x=True, border_width=0, pad=((0, 12), (0, 0))),
         sg.FolderBrowse(text(language, "browse"), key="-BROWSE_FOLDER-", target="-IN2-", size=(15, 1), button_color=(palette["text"], palette["panel_alt"]))],
    ], pad=(28, 12), background_color=palette["panel"])
    actions = panel([[
        sg.Button(text(language, "match"), key="Match", size=(15, 1), font=(FONT, 11, "bold"), border_width=0, pad=((0, 12), (0, 0))),
        sg.Button(text(language, "preview"), key="Preview", size=(14, 1), border_width=0, button_color=(palette["text"], palette["panel_alt"]), pad=((0, 12), (0, 0))),
        sg.Push(background_color=palette["panel"]),
        sg.Button(text(language, "cancel"), key="Cancel", size=(10, 1), disabled=True, border_width=0, button_color=(palette["muted"], palette["panel"])),
    ]], pad=(28, 12), background_color=palette["panel"])
    counters = panel([[
        counter_column(text(language, "matched"), "-MATCHED-", palette["success"], palette),
        counter_column(text(language, "existing"), "-EXISTING-", palette["text"], palette),
        counter_column(text(language, "errors"), "-ERRORS-", palette["danger"], palette),
        counter_column(text(language, "unmatched"), "-UNMATCHED-", palette["warning"], palette),
    ]], pad=(28, 16), background_color=palette["input_bg"])
    status = panel([
        [sg.Text(text(language, "activity"), key="-ACTIVITY_LABEL-", font=(FONT, 11, "bold"), background_color=palette["panel"], pad=((0, 0), (0, 6)))],
        [sg.Text(text(language, "ready"), key="-PROGRESS_LABEL-", size=(72, 2), expand_x=True, font=(FONT, 10), background_color=palette["panel"], text_color=palette["muted"], pad=((0, 0), (0, 6)))],
        [sg.ProgressBar(100, orientation="h", size=(48, 8), expand_x=True, border_width=0, bar_color=(palette["accent"], palette["panel_alt"]), key="-PROGRESS_BAR-", pad=((0, 0), (0, 12)))],
        [sg.Multiline(size=(74, 6), key="-LOG-", expand_x=True, expand_y=True, autoscroll=True, disabled=True, border_width=0, background_color=palette["input_bg"], text_color=palette["text"], font=("Consolas" if platform.system() == "Windows" else "Menlo", 10))],
    ], pad=(28, 12), expand_y=True, background_color=palette["panel"])
    footer = panel([[
        sg.Button(text(language, "results"), key="Results", size=(18, 1), disabled=True, button_color=(palette["text"], palette["panel_alt"]), pad=((0, 12), (0, 0))),
        sg.Button(text(language, "report"), key="Report", size=(14, 1), disabled=True, button_color=(palette["text"], palette["panel_alt"])),
        sg.Push(background_color=palette["panel"]),
        sg.Button(text(language, "about"), key="About", size=(13, 1), border_width=0,
                  button_color=(palette["muted"], palette["panel"]),
                  tooltip=text(language, "about_tip"), pad=((12, 12), (0, 0))),
        sg.Button(text(language, "support"), key="Support", size=(15, 1), border_width=0,
                  button_color=(palette["support_text"], palette["support_bg"]),
                  tooltip=text(language, "support_tip")),
    ]], pad=(28, 16), background_color=palette["panel"])
    layout = [[sg.Column([
        [header],
        [sg.HorizontalSeparator(key="-TOP_LINE-", color=palette["line"], pad=(0, 0))],
        [appearance], [settings], [actions], [counters], [status],
        [sg.HorizontalSeparator(key="-BOTTOM_LINE-", color=palette["line"], pad=(0, 0))],
        [footer],
    ], expand_x=True, expand_y=True, background_color=palette["panel"], pad=(0, 0))]]
    window = sg.Window(f"Google Photos Matcher v{APP_VERSION}", layout, icon=icon_path if platform.system() == "Windows" else None, finalize=True, background_color=palette["bg"], size=(900, 680), resizable=True, enable_close_attempted_event=True, margins=(0, 0))
    window.TKroot.minsize(780, 640)
    window.gpm_preferences, window.gpm_language, window.gpm_palette = preferences, language, palette
    window.gpm_summary, window.gpm_log = {}, deque(maxlen=1000)
    window.gpm_status = {"key": "ready", "message": None, "color": "muted"}
    _capture_color_roles(window, palette)
    _style_native_controls(window)
    _install_button_feedback(window)
    return window


def _set_busy(window, busy):
    palette = _window_palette(window)
    for key in ("Preview", "Match", "-IN2-", "-BROWSE_FOLDER-"):
        window[key].update(disabled=busy)
    window["Match"].update(button_color=(palette["muted"], palette["panel_alt"]) if busy else (palette["on_accent"], palette["accent"]))
    window["Cancel"].update(disabled=not busy)
    _refresh_button_feedback(window)


def _open_path(path):
    if platform.system() == "Windows":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", path])


def _build_backup_dialog(window, folder):
    palette = _window_palette(window)
    language = _window_language(window)
    layout = [
        [sg.Text(text(language, "backup_title"), font=(DISPLAY_FONT, 18), text_color=palette["warning"], background_color=palette["panel"], pad=((0, 0), (0, 16)))],
        [sg.Text(text(language, "backup_message"), size=(64, None), font=(FONT, 11), text_color=palette["text"], background_color=palette["panel"], pad=((0, 0), (0, 16)))],
        [sg.Text(str(folder), size=(64, 2), font=(FONT, 9), text_color=palette["muted"], background_color=palette["panel"], tooltip=str(folder), pad=((0, 0), (0, 18)))],
        [sg.Push(background_color=palette["panel"]),
         sg.Button(text(language, "cancel"), key="Cancel", size=(12, 1), bind_return_key=True, button_color=(palette["text"], palette["panel_alt"]), pad=((0, 12), (0, 0))),
         sg.Button(text(language, "backup_continue"), key="Match", size=(23, 1), button_color=(palette["on_accent"], palette["accent"]))],
    ]
    dialog = sg.Window(text(language, "backup_title"), layout, modal=True, finalize=True, background_color=palette["panel"], margins=(24, 24), keep_on_top=True)
    dialog.gpm_palette = palette
    _install_button_feedback(dialog, ("Match", "Cancel"))
    dialog.bind("<Escape>", "Cancel")
    dialog["Cancel"].Widget.focus_set()
    return dialog


def _confirm_backup(window, folder):
    dialog = _build_backup_dialog(window, folder)
    try:
        event, values = dialog.read()
        return event == "Match"
    finally:
        dialog.close()


def run_app():
    window = build_window()
    cancel_event = threading.Event()
    worker = None
    closing = False
    summary = {}
    results_folder = ""
    while True:
        event, values = window.read()
        running = worker is not None and worker.is_alive()
        if event in (sg.WIN_CLOSED, sg.WINDOW_CLOSE_ATTEMPTED_EVENT):
            if running:
                closing = True
                cancel_event.set()
                _set_status(window, key="finishing")
                continue
            break
        if event in ("Match", "Preview"):
            if running:
                continue
            folder = Path(values["-IN2-"].strip()).expanduser()
            if not values["-IN2-"].strip() or not folder.is_dir():
                _set_status(window, key="invalid_folder", color="danger")
                continue
            if event == "Match" and not _confirm_backup(window, folder):
                continue
            cancel_event.clear()
            summary = {}
            window.gpm_summary = summary
            results_folder = str(folder.resolve() / "MatchedMedia")
            _set_busy(window, True)
            window["Report"].update(disabled=True)
            window["Results"].update(disabled=True)
            window["-LOG-"].update("")
            history = getattr(window, "gpm_log", None)
            if isinstance(history, deque):
                history.clear()
            for key in ("-MATCHED-", "-EXISTING-", "-ERRORS-", "-UNMATCHED-"):
                window[key].update("0")
            _set_status(window, key="scanning", color="text")
            window["-PROGRESS_BAR-"].update(0)
            worker = threading.Thread(target=mainProcess, args=(str(folder), window, ""), kwargs={"dry_run": event == "Preview", "cancel_event": cancel_event}, daemon=True)
            worker.start()
        elif event in ("-THEME-", "-LANGUAGE-"):
            options = THEME_OPTIONS if event == "-THEME-" else LANGUAGE_OPTIONS
            labels = _choice_labels(_window_language(window), options)
            selection = values[event]
            if selection in labels:
                preferences = dict(window.gpm_preferences)
                preferences["theme" if event == "-THEME-" else "language"] = options[labels.index(selection)]
                _apply_preferences(window, preferences, persist=True)
        elif event == "Cancel":
            cancel_event.set()
            window["Cancel"].update(disabled=True)
            _refresh_button_feedback(window)
            _set_status(window, key="finishing")
        elif event == "-UPDATE_PROGRESS-":
            progress, filename = values[event]
            _set_status(window, progress=progress, filename=filename, color="text")
            window["-PROGRESS_BAR-"].update(progress)
        elif event == "-LOG-":
            _append_log(window, values[event])
        elif event == "-UPDATE_ERROR-":
            _set_status(window, message=values[event], color="danger")
            _set_busy(window, False)
            if closing:
                break
        elif event == "-UPDATE_COUNTS-":
            window.gpm_summary = values[event]
            _update_counters(window, window.gpm_summary)
        elif event == "-UPDATE_SUMMARY-":
            summary = values[event]
            window.gpm_summary = summary
            _update_counters(window, summary)
            window["Report"].update(disabled=False)
            window["Results"].update(disabled=False)
            _refresh_button_feedback(window)
        elif event == "-UPDATE_DONE-":
            label = "cancelled" if summary.get("cancelled") else "preview_done" if summary.get("dry_run") else "done"
            _set_status(window, key=label, color="danger" if summary.get("error") else "success")
            window["-PROGRESS_BAR-"].update(100)
            _set_busy(window, False)
            if closing:
                break
        elif event in ("Results", "Report"):
            path = results_folder if event == "Results" else summary.get("report")
            if path:
                try:
                    _open_path(path)
                except OSError as error:
                    _append_log(window, str(error))
        elif event in PROJECT_LINKS:
            try:
                if not webbrowser.open_new_tab(PROJECT_LINKS[event]):
                    _append_log(window, text("en", "browser_failed", detail=PROJECT_LINKS[event]))
            except (OSError, webbrowser.Error) as error:
                _append_log(window, text("en", "browser_failed", detail=error))
    window.close()


def _check_bundled_exiftool(report_path):
    try:
        executable = get_exiftool_path()
        if not executable or not Path(executable).resolve().is_relative_to(Path(resource_path("vendor/exiftool")).resolve()):
            raise FileNotFoundError("Bundled ExifTool is missing")
        with tempfile.TemporaryDirectory(prefix="gpm-bundle-check-") as folder, exiftool_batch() as session:
            process_id = None
            for index in range(2):
                image_path = str(Path(folder) / f"probe-{index}.png")
                Image.new("RGB", (8, 8), "red").save(image_path)
                set_image_metadata(image_path, 41.4, -3.7, -12, 1000000000)
                result = _run_exiftool(image_path, ["-j", "-n", "-DateTimeOriginal", "-Composite:GPSLatitude", "-Composite:GPSLongitude", "-Composite:GPSAltitude"])
                metadata = json.loads(result.stdout.decode("utf-8"))[0]
                expected_date = datetime.fromtimestamp(1000000000).strftime("%Y:%m:%d %H:%M:%S")
                if metadata.get("DateTimeOriginal") != expected_date or abs(metadata.get("GPSLatitude", 0) - 41.4) > 0.00001 or abs(metadata.get("GPSLongitude", 0) + 3.7) > 0.00001 or metadata.get("GPSAltitude") != -12:
                    raise RuntimeError("Bundled ExifTool metadata round trip failed")
                if process_id is not None and session.process.pid != process_id:
                    raise RuntimeError("Bundled ExifTool did not reuse its persistent process")
                process_id = session.process.pid
        report = {"ok": True, "exiftool": executable, "metadata": metadata, "persistent": True}
    except Exception as error:
        report = {"ok": False, "error": str(error)}
    with Path(report_path).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    return report["ok"]


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check-exiftool":
        raise SystemExit(0 if _check_bundled_exiftool(sys.argv[2]) else 1)
    run_app()