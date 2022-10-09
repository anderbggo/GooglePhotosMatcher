from main import *

sg.theme("DarkTeal2")
layout = [[sg.T("")],
          [sg.Text('Enter suffix used for edited photos (optional):')],
          [sg.InputText(key='-INPUT_TEXT-'), sg.ReadFormButton('Help')],
          [sg.T("")],
          [sg.Text("Choose a folder: ")],
          [sg.Input(key="-IN2-", change_submits=True), sg.FolderBrowse(key="-IN-")],
          [sg.T("")],
          [sg.Button("Match")],
          [sg.T("")],
          [sg.ProgressBar(100, visible=False, orientation='h', border_width=4, key='-PROGRESS_BAR-')],
          [sg.T("", key='-PROGRESS_LABEL-')]]

window = sg.Window('Google Photos Matcher', layout, icon='photos.ico')

while True:
    event, values = window.read()

    if event == sg.WIN_CLOSED or event == "Exit":
        break
    elif event == "Match":
        mainProcess(values["-IN2-"], window, values['-INPUT_TEXT-'])
    elif event == "Help":
        sg.Popup("", "Media edited with the integrated editor of google photos "
                 "will download both the original image 'Example.jpg' and the edited version 'Example-editado.jpg'.", "",
                "The 'editado' suffix changes depending on the language (in the case of Spain it will be 'editado').","",
                "If you leave this box blank default spanish suffix will be used to search for edited photos.",
                 "", title="Information", icon='photos.ico')
