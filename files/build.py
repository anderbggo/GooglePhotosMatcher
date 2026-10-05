import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXIFTOOL_VERSION = "13.59"
EXIFTOOL_ARCHIVE = f"exiftool-{EXIFTOOL_VERSION}_64.zip"
EXIFTOOL_URL = f"https://downloads.sourceforge.net/project/exiftool/{EXIFTOOL_ARCHIVE}"
EXIFTOOL_SHA256 = "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec"


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_exiftool(archive_path, destination):
    if _digest(archive_path) != EXIFTOOL_SHA256:
        raise ValueError("ExifTool SHA-256 does not match the official release; archive will not be used")
    destination = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination) or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Unsafe path in ExifTool archive")
        archive.extractall(destination)
    package = destination / f"exiftool-{EXIFTOOL_VERSION}_64"
    required = (
        package / "exiftool(-k).exe",
        package / "exiftool_files" / "perl.exe",
        package / "exiftool_files" / "exiftool.pl",
        package / "exiftool_files" / "LICENSE",
        package / "exiftool_files" / "Licenses_Strawberry_Perl.zip",
        package / "README.txt",
    )
    if not all(path.is_file() for path in required):
        raise ValueError("Incomplete ExifTool distribution")
    required[0].rename(package / "exiftool.exe")
    return package


def download_exiftool():
    cache = ROOT / "build" / "exiftool"
    cache.mkdir(parents=True, exist_ok=True)
    archive_path = cache / EXIFTOOL_ARCHIVE
    if archive_path.exists():
        if _digest(archive_path) != EXIFTOOL_SHA256:
            raise ValueError(f"Invalid cached ExifTool archive: {archive_path}")
        return archive_path
    curl = shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("curl.exe is required for downloading; alternatively use --exiftool-archive with the official ZIP")
    descriptor, filename = tempfile.mkstemp(prefix="exiftool-download-", suffix=".zip", dir=cache)
    os.close(descriptor)
    temporary = Path(filename)
    try:
        subprocess.run([
            curl, "--fail", "--location", "--connect-timeout", "20", "--max-time", "180",
            "--output", str(temporary), EXIFTOOL_URL,
        ], check=True)
        if _digest(temporary) != EXIFTOOL_SHA256:
            raise ValueError("Downloaded ExifTool SHA-256 does not match; nothing will be executed")
        temporary.replace(archive_path)
    finally:
        temporary.unlink(missing_ok=True)
    return archive_path


def build_command(package):
    return [
        sys.executable, "-m", "PyInstaller", "--noconsole", "--onefile", "--clean",
        "--hidden-import", "PySimpleGUI", "--icon", str(ROOT / "assets" / "photo.ico"),
        "--name", "GPMatcher", "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"), "--specpath", str(ROOT),
        "--add-data", f"{ROOT / 'assets' / 'photo.ico'};.",
        "--add-data", f"{package};vendor/exiftool",
        "--paths", str(ROOT / "files"), str(ROOT / "files" / "window.py"),
    ]


def main():
    parser = argparse.ArgumentParser(description="Build a standalone Windows EXE with verified ExifTool included")
    parser.add_argument("--exiftool-archive", type=Path, help="Use the official ExifTool 13.59 64-bit ZIP without downloading")
    arguments = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().casefold() not in {"amd64", "x86_64", "arm64"}:
        parser.error("This build requires 64-bit Windows; build macOS applications separately on macOS")
    archive_path = arguments.exiftool_archive or download_exiftool()
    with tempfile.TemporaryDirectory(prefix="gpm-build-exiftool-") as folder:
        package = prepare_exiftool(archive_path, Path(folder))
        version = subprocess.run(
            [str(package / "exiftool.exe"), "-config", "", "-ver"],
            check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if version.stdout.strip() != EXIFTOOL_VERSION:
            raise RuntimeError("Unexpected ExifTool version")
        print(f"Building GPMatcher with verified ExifTool {EXIFTOOL_VERSION}", flush=True)
        subprocess.run(build_command(package), check=True, cwd=ROOT)
        report = Path(folder) / "bundle-check.json"
        process = subprocess.run([str(ROOT / "dist" / "GPMatcher.exe"), "--check-exiftool", str(report)], timeout=120)
        if not report.is_file():
            raise RuntimeError("Packaged executable did not produce its ExifTool verification report")
        verification = json.loads(report.read_text(encoding="utf-8"))
        if process.returncode != 0 or not verification.get("ok"):
            raise RuntimeError(f"Packaged ExifTool verification failed: {verification.get('error', 'unknown error')}")
        print("Packaged ExifTool metadata round trip passed", flush=True)
    print(f"Ready: {ROOT / 'dist' / 'GPMatcher.exe'} (ExifTool and its licenses are included)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))