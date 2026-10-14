"""Build the command-line program for the computer this runs on.

    uv run --with pyinstaller build.py

Run this once on a Mac or on Windows. On a Mac it makes ``dist/label-generator``;
on Windows it makes ``dist/label-generator.exe``. The program comes with its own
Python and its ``config/`` files, so there is no need to install anything on the
computer that uses it.

Python 3.12, with ``pyinstaller``, ``lxml`` and ``python-docx``, is needed, and
the command above has uv provide them.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

CLI = Path(__file__).resolve().parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="label-generator-build-") as scratch:
        command = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--onefile", "--console",
            "--name", "label-generator",
            "--paths", str(CLI),
            "--add-data", f"{CLI / 'config'}{os.pathsep}config",
            "--distpath", str(CLI / "dist"),
            "--workpath", scratch, "--specpath", scratch,
            str(CLI / "main.py"),
        ]
        return subprocess.run(command).returncode


if __name__ == "__main__":
    raise SystemExit(main())
