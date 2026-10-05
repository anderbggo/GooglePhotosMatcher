import io
import os
import sys
import threading
import tkinter

import PySimpleGUI as sg
from PIL import Image

from auxFunctions import resource_path
from main import mainProcess


if sys.version_info >= (3, 14):
    def _trace_compatibility(self, mode, callback):
        trace_modes = {"r": "read", "w": "write", "u": "unset"}
        return self.trace_add(trace_modes.get(mode, mode), callback)

    tkinter.Variable.trace = _trace_compatibility
    tkinter.Variable.trace_variable = _trace_compatibility


PALETTE = {
    "bg": "#0F172A",
    "panel": "#111827",
    "panel_alt": "#1E293B",
    "text": "#E5EEF8",
    "muted": "#94A3B8",
    "accent": "#38BDF8",
    "accent_soft": "#0EA5E9",
    "success": "#86EFAC",
    "danger": "#FCA5A5",
    "input_bg": "#0B1120",
}

sg.theme_add_new(
    "GPMatcherMac",
    {
        "BACKGROUND": PALETTE["bg"],
        "TEXT": PALETTE["text"],
        "INPUT": PALETTE["input_bg"],
        "TEXT_INPUT": PALETTE["text"],
        "SCROLL": PALETTE["accent"],
        "BUTTON": (PALETTE["text"], PALETTE["accent_soft"]),
        "PROGRESS": (PALETTE["accent"], PALETTE["panel_alt"]),
        "BORDER": 0,
        "SLIDER_DEPTH": 0,
        "PROGRESS_DEPTH": 0,
    },
)
sg.theme("GPMatcherMac")
sg.set_options(
    font=("Helvetica", 11),
    element_padding=(0, 0),
    margins=(0, 0),
    background_color=PALETTE["bg"],
)

icon_path = resource_path("assets/photo.ico")
if not os.path.exists(icon_path):
    icon_path = resource_path("photo.ico")


def load_logo_data(path, size=(72, 72)):
    with Image.open(path) as logo_image:
        logo_image = logo_image.convert("RGBA")
        logo_image.thumbnail(size)
        buffer = io.BytesIO()
        logo_image.save(buffer, format="PNG")
        return buffer.getvalue()


def panel(content, pad=(24, 0)):
    return sg.Column(
        content,
        background_color=PALETTE["panel"],
        pad=pad,
        expand_x=True,
        element_justification="left",
        vertical_alignment="top",
    )


def show_modal(title, message, button_text="OK"):
    modal = sg.Window(
        title,
        [[sg.Column(
            [
                [sg.Text(title, font=("Helvetica", 16), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
                [sg.Text(message, size=(48, None), background_color=PALETTE["panel"], text_color=PALETTE["muted"])],
                [sg.Push(background_color=PALETTE["panel"]), sg.Button(button_text, size=(10, 1), border_width=0)],
            ],
            background_color=PALETTE["panel"],
            pad=(24, 24),
        )]],
        modal=True,
        keep_on_top=True,
        background_color=PALETTE["bg"],
        finalize=True,
    )
    modal.read()
    modal.close()


logo_data = load_logo_data(icon_path)
header = panel([
    [
        sg.Image(data=logo_data, background_color=PALETTE["panel"], pad=((0, 18), (0, 0))),
        sg.Column([
            [sg.Text("Google Photos Matcher", font=("Helvetica", 24), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
            [sg.Text("Restore metadata and organize your Google Takeout photos with a cleaner, more modern interface.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (8, 0)))],
        ], background_color=PALETTE["panel"], pad=(0, 0)),
    ],
], pad=(24, 24))

settings_panel = panel([
    [sg.Text("Edited photo suffix", font=("Helvetica", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
    [sg.Text("Optional. Enter a different suffix if your Google Photos export uses one for edited photos.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (6, 12)))],
    [
        sg.Input(key="-INPUT_TEXT-", size=(32, 1), border_width=0, background_color=PALETTE["input_bg"], text_color=PALETTE["text"], pad=((0, 12), (0, 0))),
        sg.Button("How it works", key="Help", border_width=0, button_color=(PALETTE["text"], PALETTE["panel_alt"])),
    ],
])

folder_panel = panel([
    [sg.Text("Google Takeout folder", font=("Helvetica", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
    [sg.Text("Select the root export folder or any subfolder containing images and JSON sidecars.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (6, 12)))],
    [
        sg.Input(key="-IN2-", change_submits=True, expand_x=True, border_width=0, background_color=PALETTE["input_bg"], text_color=PALETTE["text"], pad=((0, 12), (0, 0))),
        sg.FolderBrowse("Browse", key="-IN-", button_color=(PALETTE["text"], PALETTE["panel_alt"])),
    ],
])

exiftool_panel = panel([
    [sg.Text("ExifTool path", font=("Helvetica", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
    [sg.Text("Optional. Browse to the ExifTool binary if it is not available on your PATH.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (6, 12)))],
    [
        sg.Input(key="-EXIFTOOL_PATH-", expand_x=True, border_width=0, background_color=PALETTE["input_bg"], text_color=PALETTE["text"], pad=((0, 12), (0, 0))),
        sg.FileBrowse("Browse", target="-EXIFTOOL_PATH-", button_color=(PALETTE["text"], PALETTE["panel_alt"])),
    ],
])

action_panel = panel([
    [sg.Button("Start matching", key="Match", size=(16, 1), border_width=0, mouseover_colors=(PALETTE["text"], PALETTE["accent"]))],
    [sg.Text("Processed files appear in MatchedMedia; edited originals go to EditedRaw.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (12, 0)))],
], pad=(24, 18))

status_panel = panel([
    [sg.Text("Status", font=("Helvetica", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
    [sg.Text("Waiting for a folder to begin.", key="-PROGRESS_LABEL-", size=(60, 1), background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (10, 12)))],
    [sg.ProgressBar(100, orientation="h", size=(48, 14), border_width=0, bar_color=(PALETTE["accent"], PALETTE["panel_alt"]), key="-PROGRESS_BAR-")],
    [sg.Text("Activity log", font=("Helvetica", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"], pad=((0, 0), (20, 10)))],
    [sg.Multiline(size=(74, 10), key="-LOG-", autoscroll=True, disabled=True, visible=False, border_width=0, background_color=PALETTE["input_bg"], text_color="#D6E3F0", font=("Menlo", 9))],
], pad=(24, 0))

layout = [[sg.Column([[header], [settings_panel], [folder_panel], [exiftool_panel], [action_panel], [status_panel]], background_color=PALETTE["bg"], expand_x=True, pad=(0, 0))]]
window = sg.Window("Google Photos Matcher", layout, finalize=True, background_color=PALETTE["bg"], size=(860, 720), resizable=True, margins=(0, 0))

while True:
    event, values = window.read()
    if event == sg.WIN_CLOSED:
        break
    if event == "Match":
        if not values["-IN2-"]:
            show_modal("Folder required", "Select the folder that contains your Google Photos export first.")
            continue
        window["Match"].update(disabled=True)
        window["-PROGRESS_LABEL-"].update("Initializing scan...", text_color=PALETTE["text"])
        window["-PROGRESS_BAR-"].update(0)
        threading.Thread(target=mainProcess, args=(values["-IN2-"], window, values["-INPUT_TEXT-"], values["-EXIFTOOL_PATH-"]), daemon=True).start()
    elif event == "-UPDATE_PROGRESS-":
        progress, filename = values[event]
        window["-PROGRESS_LABEL-"].update(f"Processing {progress}%  |  {filename}", text_color=PALETTE["text"])
        window["-PROGRESS_BAR-"].update(progress)
    elif event == "-LOG-":
        window["-LOG-"].update(visible=True)
        window["-LOG-"].print(values[event])
    elif event == "-UPDATE_ERROR-":
        window["-PROGRESS_LABEL-"].update(values[event], text_color=PALETTE["danger"])
        window["Match"].update(disabled=False)
    elif event == "-UPDATE_DONE-":
        success, errors = values[event]
        window["-PROGRESS_BAR-"].update(100)
        window["-PROGRESS_LABEL-"].update(f"Process complete. {success} matches restored, {errors} errors.", text_color=PALETTE["success"])
        window["Match"].update(disabled=False)
    elif event == "Help":
        show_modal("Edited photo suffix", "GPMatcher uses this suffix to identify edited images. Leave it blank to use 'editado' by default.", button_text="Got it")

window.close()
