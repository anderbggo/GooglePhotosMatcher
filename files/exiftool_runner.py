"""Locates ExifTool and runs it, reusing one persistent process per batch."""
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager


def resource_path(relative_path: str) -> str:
    """ Finds the actual path to the resource file for PyInstaller (_MEIPASS) """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def get_exiftool_path(exiftool_path=None) -> str | None:
    """ Retrieves the path for the ExifTool binary """
    if exiftool_path:
        exiftool_path = os.path.abspath(os.path.expanduser(exiftool_path.strip().strip('"')))
        if os.path.isfile(exiftool_path) and os.access(exiftool_path, os.X_OK):
            return exiftool_path
        raise FileNotFoundError(f"ExifTool not found at {exiftool_path}")

    base_paths = [resource_path("vendor/exiftool"), resource_path("")]
    if getattr(sys, "frozen", False):
        base_paths.append(os.path.dirname(sys.executable))

    exiftool_names = ["exiftool.exe", "exiftool"] if platform.system() == "Windows" else ["exiftool"]
    for base_path in base_paths:
        for exiftool_name in exiftool_names:
            candidate = os.path.normpath(os.path.join(base_path, exiftool_name))
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

    candidate = shutil.which("exiftool")
    if candidate:
        return candidate

    return None


_exiftool_state = threading.local()


class ExifToolSession:
    def __init__(self, timeout=60):
        self.timeout = timeout
        self.process = None
        self.executable = None
        self.output = None
        self.readers = []
        self.command_id = 0

    def _start(self, executable):
        if self.process is not None:
            if self.executable == executable and self.process.poll() is None:
                return
            self.close()
        self.executable = executable
        self.output = queue.Queue()
        self.process = subprocess.Popen(
            [executable, "-config", "", "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {"start_new_session": True}),
        )
        self.readers = []
        for name, stream in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
            reader = threading.Thread(target=self._read_output, args=(name, stream, self.output), daemon=True)
            self.readers.append(reader)
            reader.start()

    @staticmethod
    def _read_output(name, stream, output):
        try:
            for line in iter(stream.readline, b""):
                output.put((name, line))
        finally:
            output.put((name, None))

    def execute(self, executable, filepath, options):
        started = time.monotonic()
        try:
            self._start(executable)
            self.command_id += 1
            command = str(self.command_id)
            ready = f"{{ready{command}}}".encode("ascii")
            status_pattern = re.compile(rb"\{gpm_status_" + command.encode("ascii") + rb":(\d+)\}")
            arguments = ["-charset", "filename=UTF8", "-echo4", f"{{gpm_status_{command}:${{status}}}}", *options, os.path.abspath(filepath), f"-execute{command}"]
            self.process.stdin.write(("\n".join(arguments) + "\n").encode("utf-8"))
            self.process.stdin.flush()
            stdout, stderr = [], []
            stdout_done, returncode = False, None
            while not stdout_done or returncode is None:
                remaining = self.timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise queue.Empty
                name, line = self.output.get(timeout=remaining)
                if line is None:
                    if name == "stdout" and stdout_done or name == "stderr" and returncode is not None:
                        continue
                    raise RuntimeError("ExifTool ended before completing the current operation")
                if name == "stdout" and line.strip() == ready:
                    stdout_done = True
                elif name == "stderr" and (status := status_pattern.fullmatch(line.strip())):
                    returncode = int(status.group(1))
                else:
                    (stdout if name == "stdout" else stderr).append(line)
            return subprocess.CompletedProcess([executable, *options, filepath], returncode, b"".join(stdout), b"".join(stderr))
        except queue.Empty as error:
            self.close(force=True)
            raise RuntimeError(f"ExifTool timed out after {self.timeout:g} seconds: {os.path.basename(filepath)}") from error
        except Exception:
            self.close(force=True)
            raise

    def close(self, force=False):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None and not force:
                try:
                    process.stdin.write(b"-stay_open\nFalse\n")
                    process.stdin.flush()
                    process.wait(timeout=3)
                except (OSError, subprocess.SubprocessError):
                    force = True
            if process.poll() is None:
                if platform.system() == "Windows":
                    taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
                    try:
                        subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                    except (OSError, subprocess.SubprocessError):
                        pass
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        finally:
            for reader in self.readers:
                reader.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            self.readers = []


@contextmanager
def exiftool_batch():
    previous = getattr(_exiftool_state, "session", None)
    session = ExifToolSession()
    _exiftool_state.session = session
    try:
        yield session
    finally:
        _exiftool_state.session = previous
        session.close()


def run_exiftool(filepath, options, exiftool_path=None):
    executable = get_exiftool_path(exiftool_path)
    if not executable:
        raise FileNotFoundError("ExifTool is required for this file. Use the standalone build, or install ExifTool on PATH when running the Python source.")
    args = [executable, "-config", "", "-charset", "filename=UTF8", *options, "--", os.path.abspath(filepath)]
    try:
        session = getattr(_exiftool_state, "session", None)
        if session is not None and not any(character in argument for argument in [*options, os.path.abspath(filepath)] for character in "\r\n\0"):
            result = session.execute(executable, filepath, options)
        else:
            result = subprocess.run(
                args,
                timeout=60,
                capture_output=True,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}),
            )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"ExifTool timed out after 60 seconds: {os.path.basename(filepath)}") from error
    if result.returncode != 0:
        details = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ExifTool failed: {details or 'unknown error'}")
    return result


def write_exiftool_tags(filepath, tags, exiftool_path=None, extra_options=()):
    options = ["-overwrite_original", *extra_options]
    options.extend(f"-{key}={value}" for key, value in tags.items() if value != "")
    result = run_exiftool(filepath, options, exiftool_path)
    warnings = result.stderr.decode("utf-8", errors="replace").strip()
    if re.search(r"error converting|isn't writable|not writable|not defined", warnings, flags=re.IGNORECASE):
        raise RuntimeError(f"ExifTool could not write requested metadata: {warnings}")
