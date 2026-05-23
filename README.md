# Google Photos Matcher (v2.1)

> Simple tool to restore metadata (date, GPS coordinates, etc.) from Google Photos JSON files back into your original images and videos — just like [MetadataFixer](https://metadatafixer.com/pricing), but **free and open source**!
>
> <img width="857" height="592" alt="image" src="https://github.com/user-attachments/assets/256f0470-0095-4167-854f-2994d360993b" />


---

## How it works 📖

When you download media from Google Photos via Takeout, the files lose important metadata such as the date taken and GPS coordinates. Google stores this data separately in `.json` sidecar files.

**GPMatcher** reads those JSONs and writes the metadata back into your photos and videos automatically.

---

## Usage (EXE — no setup required) 🚀

1. Download your _Google Photos_ media from [Google Takeout](https://takeout.google.com/)

2. Download and run **GPMatcher.exe** — no installation, Python, or additional libraries needed. The EXE is fully standalone.

3. _(Optional)_ Enter the custom suffix used for edited photos (explained inside the app)

4. _(Optional)_ Select the path for ExifTool.exe if it gets stuck matching videos. Extract it from [here](https://sourceforge.net/projects/exiftool/files/)

5. Select the folder containing your images/videos and their JSONs (e.g. `Photos from 2022` or the root `Takeout` folder)

   > The app will automatically scan all subfolders

6. Click the **Match** button

7. Your matched files will appear in a `Matched` folder inside the selected directory

---

## FAQs ❓

### Why is there a folder called _EditedRaw_?

Photos edited in Google Photos have two versions:

| Folder | Content |
|--------|---------|
| `Matched` | Edited version |
| `EditedRaw` | Original (unedited) version |

### Why do some files stay unmatched?

Special characters in filenames can prevent the algorithm from matching them. To fix this:

1. Rename both the image and its JSON — e.g. `%E&xample.jpg` → `Example.jpg` and `%E&xample.json` → `Example.json`
2. Open the JSON and update the `title` field to match the new filename
3. Run GPMatcher again

---

## For developers 🛠️

> **Prerequisites:** Create a virtual environment at the root of the project first:
> ```
> python -m venv venv
> venv\Scripts\activate
> ```

### Option A — Build the .exe

1. Install build dependencies:
   ```
   pip install -r "requirements-dev.txt"
   ```

2. _(Optional)_ Download **exiftool** for Windows (64-bit): [direct download](https://sourceforge.net/projects/exiftool/files/exiftool-13.55_64.zip/download) or visit [exiftool.org](https://exiftool.org/)

3. _(Optional)_ If you want to bundle ExifTool into the EXE, rename `exiftool(-k).exe` → `exiftool.exe` and place it alongside the `exiftool_files` folder at the project root.

4. Run this command from the project root:
   ```
   pyinstaller --noconsole --onefile --clean --hidden-import PySimpleGUI --icon=assets/photo.ico --name "GPMatcher" --distpath "." --add-data "assets/photo.ico;." --paths files files/window.py
   ```

`GPMatcher.exe` will appear at the project root — ready to use!

### Option B — Run without building

1. Install runtime dependencies:
   ```
   pip install -r "requirements.txt"
   ```

2. Run:
   ```
   python files/window.py
   ```

---

## Contributors ✒️

- **[anderbggo](https://github.com/anderbggo)** — Author
- **[Kadawatcha](https://github.com/Kadawatcha)** — Contributor
- **[Golde2341](https://github.com/Golde2341)** — Contributor

## Buy me a coffee ☕

[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-☕-yellow)](https://buymeacoffee.com/anderbggo)
