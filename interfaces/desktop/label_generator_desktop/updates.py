"""Updates for installed desktop copies.

A packaged application has no package manager to tell staff that a newer build
exists, so it reads a small JSON manifest published beside its releases. The
manifest names the newest version and, for each platform, the zip that holds it:

    {
      "version": "2.1.0",
      "url": "https://example.org/releases/latest",
      "notes": "What changed.",
      "files": {
        "windows-x64": {"name": "label-generator-windows-x64.zip", "sha256": "..."},
        "macos-arm64": {"name": "label-generator-macos-arm64.zip", "sha256": "..."}
      }
    }

A file name is read relative to the manifest's own address. The manifest and its
zips live in one place, an https address or a folder (a plain path or a file://
address), and the application is given that place once, when it is assembled.

The check is off unless a manifest address is configured, never raises, and never
blocks label work. When the manifest carries a zip for the running platform, the
interface offers "Install and restart": the zip is downloaded, checked against
its sha256, unpacked and staged beside the last working version. The launcher
activates it once the new interface opens.

All of this is separate from reading a finding aid. Label generation never
touches the network under any configuration.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin
from urllib.request import urlopen

from . import recovery
from .recovery import Install, find_install

from label_generator.content import add as add_content, say

add_content(Path(__file__).with_name("config") / "content.toml")

#: Set this to the address of the published manifest to switch the check on.
MANIFEST_URL_ENV = "LABEL_GENERATOR_UPDATE_URL"

DEFAULT_TIMEOUT_SECONDS = 3.0
DOWNLOAD_TIMEOUT_SECONDS = 30.0
CHUNK_BYTES = 1 << 20

_VERSION_PART = re.compile(r"\d+")


@dataclass(frozen=True)
class UpdateInfo:
    """What the manifest says, compared against the running build."""

    current: str
    latest: str
    url: str
    notes: str = ""
    #: Where this platform's zip is, and its sha256; empty when the manifest names none.
    file_url: str = ""
    sha256: str = ""

    @property
    def is_newer(self) -> bool:
        """True when the latest release has a higher version than the one running."""
        return version_tuple(self.latest) > version_tuple(self.current)


def version_tuple(version: str) -> tuple[int, ...]:
    """Compare versions on their numeric parts, ignoring any suffix.

    Release tags for this application are plain numbers, and a comparison nobody
    can predict is worse than one that is obviously limited.
    """
    parts = tuple(int(p) for p in _VERSION_PART.findall(version or ""))
    return parts or (0,)


def manifest_url(explicit: Optional[str] = None) -> str:
    """Resolve the manifest address from the argument or the environment."""
    return (explicit or os.environ.get(MANIFEST_URL_ENV, "")).strip()


def as_location(text: str) -> str:
    """An address as a URL: a plain file path becomes a file:// address."""
    text = text.strip()
    if "://" in text:
        return text
    return Path(text).expanduser().resolve().as_uri()


# ------------------------------------------------------------------------- the check

def parse_manifest(
    payload: dict,
    current_version: str,
    *,
    source: str = "",
    target: str = "",
) -> Optional[UpdateInfo]:
    """Turn manifest JSON into an ``UpdateInfo``, or ``None`` if unusable."""
    if not isinstance(payload, dict):
        return None
    latest = str(payload.get("version") or "").strip()
    if not latest:
        return None
    file_url, sha256 = "", ""
    files = payload.get("files")
    entry = files.get(target) if isinstance(files, dict) else None
    if isinstance(entry, dict) and entry.get("name"):
        file_url = urljoin(source, str(entry["name"])) if source else str(entry["name"])
        sha256 = str(entry.get("sha256") or "").strip().lower()
    return UpdateInfo(
        current=current_version,
        latest=latest,
        url=str(payload.get("url") or "").strip(),
        notes=str(payload.get("notes") or "").strip(),
        file_url=file_url,
        sha256=sha256,
    )


def check_for_updates(
    current_version: str,
    *,
    url: Optional[str] = None,
    target: str = "",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Optional[Callable[..., object]] = None,
) -> Optional[UpdateInfo]:
    """Return update information, or ``None`` when there is nothing to report.

    ``None`` covers every uninteresting case: no manifest configured, the host
    unreachable, a malformed document, or a manifest that is not newer than the
    running build.
    """
    configured = manifest_url(url)
    if not configured:
        return None
    source = as_location(configured)
    fetch = opener or urlopen
    try:
        with fetch(source, timeout=timeout) as response:  # type: ignore[operator]
            payload = json.loads(response.read().decode("utf-8"))
        info = parse_manifest(payload, current_version, source=source, target=target)
        return info if info and info.is_newer else None
    except Exception:
        # An update check is a convenience. It must never interrupt label work.
        return None


def describe(info: Optional[UpdateInfo]) -> str:
    """One line suitable for a status area or the terminal."""
    if info is None:
        return ""
    line = say("desktop.update_available", latest=info.latest, current=info.current)
    if info.url and not info.file_url:
        line += " " + say("desktop.update_link", url=info.url)
    return line


# ------------------------------------------------------------------------ installing

def download(
    source: str,
    destination: Path,
    *,
    expected_sha256: str,
    opener: Optional[Callable[..., object]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Only accept a download with a complete, matching published digest."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError(say("desktop.update_digest_missing"))
    fetch = opener or urlopen
    digest = hashlib.sha256()
    done = 0
    with fetch(source, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:  # type: ignore[operator]
        total = int(getattr(response, "headers", {}).get("Content-Length") or 0)
        with destination.open("wb") as out:
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if digest.hexdigest() != expected_sha256.lower():
        raise ValueError(say("desktop.update_checksum"))


def extract(archive: Path, into: Path) -> Path:
    """Unpack the zip, restore executable bits, and return the application folder."""
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            parts = member.filename.rstrip("/").split("/")
            if any(p in ("", ".", "..") for p in parts) or any(c in member.filename for c in ("\\", ":")):
                raise ValueError(say("desktop.update_layout"))
            extracted = Path(bundle.extract(member, into))
            mode = (member.external_attr >> 16) & 0o777
            if mode and not member.is_dir():
                extracted.chmod(mode)
    folders = [p for p in into.iterdir() if p.is_dir()]
    if len(folders) != 1:
        raise ValueError(say("desktop.update_layout"))
    return folders[0]


def verify_runtime(interpreter: Path, version: str) -> None:
    """Ask the staged interpreter to import the desktop entry point before closing the working app."""
    probe = ("from label_generator_desktop import __version__; "
             "from label_generator_desktop.app import main; print(__version__)")
    result = subprocess.run([str(interpreter), "-I", "-c", probe], timeout=30,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or result.stdout.strip() != version.encode():
        raise ValueError(say("desktop.update_package"))


class Updater:
    """Downloads and installs one update on a background thread."""

    def __init__(
        self,
        info: UpdateInfo,
        install: Install,
        *,
        on_ready: Optional[Callable[[], None]] = None,
        opener: Optional[Callable[..., object]] = None,
        stage: Path,
    ) -> None:
        self.info = info
        self.install = install
        self._on_ready = on_ready
        self._opener = opener
        self.stage = stage
        self._lock = threading.Lock()
        self._state = "available"
        self._message = ""
        self._thread: Optional[threading.Thread] = None

    def status(self) -> dict:
        """The state the interface shows: available, working, restarting or error."""
        with self._lock:
            return {"state": self._state, "message": self._message, "version": self.info.latest}

    def _set(self, state: str, message: str) -> None:
        with self._lock:
            self._state, self._message = state, message

    def start(self) -> dict:
        """Begin installing, unless that is already under way."""
        with self._lock:
            if self._state in ("working", "restarting"):
                return {"state": self._state, "message": self._message, "version": self.info.latest}
            self._state, self._message = "working", say("desktop.update_downloading")
            self._thread = threading.Thread(target=self._run, name="label-generator-update", daemon=True)
            self._thread.start()
        return self.status()

    def _run(self) -> None:
        created = False
        try:
            self.stage.mkdir(mode=0o700)
            created = True
            archive = self.stage / "update.zip"

            def progress(done: int, total: int) -> None:
                mb = done >> 20
                text = (say("desktop.update_progress", done=mb, total=total >> 20)
                        if total else say("desktop.update_downloading"))
                self._set("working", text)

            download(self.info.file_url, archive, expected_sha256=self.info.sha256,
                     opener=self._opener, progress=progress)
            self._set("working", say("desktop.update_installing"))
            source = extract(archive, self.stage / "unpacked")
            package = self.install.package(self.stage)
            if source.name != package.root.name:
                raise ValueError(say("desktop.update_layout"))
            source.rename(package.root)
            try:
                interpreter = package.check(self.info.latest)
                verify_runtime(interpreter, self.info.latest)
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                raise ValueError(say("desktop.update_package")) from exc
            archive.unlink()
            shutil.rmtree(self.stage / "unpacked")
            recovery.write_marker(self.stage / "version", self.info.latest)
        except Exception as exc:  # reported to the person, never raised into the service
            if created:
                shutil.rmtree(self.stage, ignore_errors=True)
            self._set("error", say("desktop.update_failed", reason=exc))
            return
        self._set("restarting", say("desktop.update_restarting"))
        if self._on_ready:
            self._on_ready()


def make_updater(
    info: Optional[UpdateInfo],
    *,
    on_ready: Optional[Callable[[], None]] = None,
) -> Optional[Updater]:
    """An ``Updater`` when this is an assembled copy and the manifest has its zip."""
    stage = os.environ.get(recovery.STAGE)
    if info is None or not info.file_url or not stage:
        return None
    install = find_install()
    if install is None:
        return None
    return Updater(info, install, stage=Path(stage), on_ready=on_ready)
