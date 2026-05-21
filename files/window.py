import threading
import PySimpleGUI as sg
from main import mainProcess
import ctypes
from auxFunctions import resource_path
import os
import io
from PIL import Image

# High definition of the window (very very very better UI )
ctypes.windll.shcore.SetProcessDpiAwareness(1)

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
    "GPMatcherModern",
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
sg.theme("GPMatcherModern")
sg.set_options(
    font=("Segoe UI", 11),
    element_padding=(0, 0),
    margins=(0, 0),
    background_color=PALETTE["bg"],
)

# serch logo (for compatibility windows and python)
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


logo_data = load_logo_data(icon_path)


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
    modal_layout = [
        [
            sg.Column(
                [
                    [sg.Text(title, font=("Segoe UI Semibold", 16), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
                    [sg.Text(message, size=(48, None), background_color=PALETTE["panel"], text_color=PALETTE["muted"])],
                    [sg.Push(background_color=PALETTE["panel"]), sg.Button(button_text, size=(10, 1), border_width=0)],
                ],
                background_color=PALETTE["panel"],
                pad=(24, 24),
            )
        ]
    ]
    modal = sg.Window(
        title,
        modal_layout,
        icon=icon_path,
        modal=True,
        no_titlebar=False,
        keep_on_top=True,
        background_color=PALETTE["bg"],
        finalize=True,
    )
    modal.read()
    modal.close()


header = panel(
    [
        [
            sg.Image(data=logo_data, background_color=PALETTE["panel"], pad=((0, 18), (0, 0))),
            sg.Column(
                [
                    [sg.Text("Google Photos Matcher", font=("Segoe UI Semibold", 24), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
                    [sg.Text("Restore metadata and organize your Google Takeout photos with a cleaner, more modern interface.", font=("Segoe UI", 11), background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (8, 0)))],
                ],
                background_color=PALETTE["panel"],
                pad=(0, 0),
            ),
        ],
    ],
    pad=(24, 24),
)

settings_panel = panel(
    [
        [sg.Text("Edited photo suffix", font=("Segoe UI Semibold", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
        [sg.Text("Optional. If your Google Photos export uses a different suffix for edited photos, enter it here.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (6, 12)))],
        [
            sg.Input(
                key="-INPUT_TEXT-",
                size=(32, 1),
                border_width=0,
                background_color=PALETTE["input_bg"],
                text_color=PALETTE["text"],
                pad=((0, 12), (0, 0)),
            ),
            sg.Button("How it works", key="Help", border_width=0, button_color=(PALETTE["text"], PALETTE["panel_alt"])),
        ],
    ]
)

folder_panel = panel(
    [
        [sg.Text("Google Takeout folder", font=("Segoe UI Semibold", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
        [sg.Text("Select the root export folder or any subfolder that contains images and JSON sidecars.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (6, 12)))],
        [
            sg.Input(
                key="-IN2-",
                change_submits=True,
                expand_x=True,
                border_width=0,
                background_color=PALETTE["input_bg"],
                text_color=PALETTE["text"],
                pad=((0, 12), (0, 0)),
            ),
            sg.FolderBrowse(
                "Browse",
                key="-IN-",
                button_color=(PALETTE["text"], PALETTE["panel_alt"]),
            ),
        ],
    ]
)

exiftool_panel = panel(
    [
        [sg.Text("ExifTool path", font=("Segoe UI Semibold", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
        [sg.Text("Optional. If you already have ExifTool installed. Browse to exiftool.exe.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (6, 12)))],
        [
            sg.Input(
                key="-EXIFTOOL_PATH-",
                expand_x=True,
                border_width=0,
                background_color=PALETTE["input_bg"],
                text_color=PALETTE["text"],
                pad=((0, 12), (0, 0)),
            ),
            sg.FileBrowse(
                "Browse",
                target="-EXIFTOOL_PATH-",
                file_types=([("Executable", "*.exe")]),
                button_color=(PALETTE["text"], PALETTE["panel_alt"]),
            ),
        ],
    ]
)

action_panel = panel(
    [
        [sg.Button("Start matching", key="Match", size=(16, 1), border_width=0, mouseover_colors=(PALETTE["text"], PALETTE["accent"]))],
        [sg.Text("Results will appear in the MatchedMedia and EditedRaw folders inside the selected directory.", background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (12, 0)))],
    ],
    pad=(24, 18),
)

status_panel = panel(
    [
        [sg.Text("Status", font=("Segoe UI Semibold", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"])],
        [sg.Text("Waiting for a folder to begin.", key="-PROGRESS_LABEL-", size=(60, 1), background_color=PALETTE["panel"], text_color=PALETTE["muted"], pad=((0, 0), (10, 12)))],
        [sg.ProgressBar(100, orientation="h", size=(48, 14), border_width=0, bar_color=(PALETTE["accent"], PALETTE["panel_alt"]), key="-PROGRESS_BAR-")],
        [sg.Text("Activity log", font=("Segoe UI Semibold", 13), background_color=PALETTE["panel"], text_color=PALETTE["text"], pad=((0, 0), (20, 10)))],
        [
            sg.Multiline(
                size=(74, 10),
                key="-LOG-",
                autoscroll=True,
                disabled=True,
                visible=False,
                border_width=0,
                background_color=PALETTE["input_bg"],
                text_color="#D6E3F0",
                font=("Consolas", 9),
            )
        ],
    ],
    pad=(24, 0),
)

layout = [
    [sg.Column([[header], [settings_panel], [folder_panel], [exiftool_panel], [action_panel], [status_panel]], background_color=PALETTE["bg"], expand_x=True, pad=(0, 0))],
]

window = sg.Window(
    "Google Photos Matcher",
    layout,
    icon=icon_path,
    finalize=True,
    background_color=PALETTE["bg"],
    size=(860, 720),
    resizable=True,
    margins=(0, 0),
)

while True:
    event, values = window.read()

    if event == sg.WIN_CLOSED:
        break
        
    elif event == "Match":
        if not values["-IN2-"]:
            show_modal("Folder required", "Select the folder that contains your Google Photos export first.")
            continue
            
        window['Match'].update(disabled=True)
        window['-PROGRESS_LABEL-'].update("Initializing scan...", text_color=PALETTE["text"])
        window['-PROGRESS_BAR-'].update(0)
        
        # Start processing in a separate thread to keep UI responsive
        threading.Thread(
            target=mainProcess, 
            args=(values["-IN2-"], window, values['-INPUT_TEXT-'], values['-EXIFTOOL_PATH-']), 
            daemon=True
        ).start()

    elif event == '-UPDATE_PROGRESS-':
        progress, filename = values[event]
        window['-PROGRESS_LABEL-'].update(f"Processing {progress}%  |  {filename}", text_color=PALETTE["text"])
        window['-PROGRESS_BAR-'].update(progress)
    elif event == '-LOG-':
        window['-LOG-'].update(visible=True)
        window['-LOG-'].print(values[event])
    elif event == '-UPDATE_ERROR-':
        window['-PROGRESS_LABEL-'].update(values[event], text_color=PALETTE['danger'])
        window['Match'].update(disabled=False)

    elif event == '-UPDATE_DONE-':
        success, errors = values[event]
        window['-PROGRESS_BAR-'].update(100)
        msg = f"Process complete. {success} matches restored, {errors} errors."
        window['-PROGRESS_LABEL-'].update(msg, text_color=PALETTE['success'])
        window['Match'].update(disabled=False)

    elif event == "Help":
        show_modal(
            "Edited photo suffix",
            "GPMatcher needs to know which suffix Google Photos uses for edited images. Common examples include 'editado' in Spanish or 'modifie' in French. If you are not sure, leave it blank and 'editado' will be used by default.",
            button_text="Got it",
        )

window.close()