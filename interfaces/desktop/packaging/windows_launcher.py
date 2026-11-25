"""Build with Windows PyInstaller --onefile --windowed --name label-generator-desktop
and --add-data "label-generator-windows-x64.zip;." from the assembler's output.
"""

import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile


def unpack_runtime(archive: Path, cache: Path) -> Path:
    with archive.open("rb") as source:
        identifier = hashlib.file_digest(source, "sha256").hexdigest()[:24]
    destination = cache / identifier
    if not destination.is_dir():
        with tempfile.TemporaryDirectory(dir=cache) as scratch:
            with ZipFile(archive) as bundle:
                bundle.extractall(scratch)
            try:
                (Path(scratch) / "Label Generator").rename(destination)
            except FileExistsError:
                # Another launcher completed extraction first.
                pass
    return destination / "python" / "python.exe"


def main() -> int:
    cache = Path(os.environ["LOCALAPPDATA"]) / "Label Generator" / "desktop"
    cache.mkdir(parents=True, exist_ok=True)
    archive = Path(__file__).with_name("label-generator-windows-x64.zip")
    python = unpack_runtime(archive, cache)
    env = os.environ.copy()
    feed = Path(sys.executable).parent / "Updates" / "latest.json"
    env.setdefault("LABEL_GENERATOR_UPDATE_URL", str(feed))
    # Let the bundled interpreter load its own Windows DLLs.
    ctypes.windll.kernel32.SetDllDirectoryW(None)
    with tempfile.NamedTemporaryFile(dir=cache, prefix="startup-", suffix=".log", delete=False) as log:
        log_path = Path(log.name)
        process = subprocess.run(
            [str(python), "-I", "-m", "label_generator_desktop", *sys.argv[1:]],
            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    if process.returncode:
        raise RuntimeError(f"The desktop app stopped. Startup details are in:\n{log_path}")
    log_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), "Label Generator", 0x10)
        sys.exit(1)
