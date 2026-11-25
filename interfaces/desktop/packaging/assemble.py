#!/usr/bin/env python3
"""Assemble a self-contained Label Generator application for any supported platform.

The application carries its own Python. A relocatable CPython distribution is fetched
for the target, this application is installed into it as wheels resolved
for that target, and a launcher is written for the platform's conventions. Nothing on
the machine that runs the result needs Python, and nothing on the machine that builds
it needs to be the target platform: wheels are resolved, not compiled, so one host
produces every platform.

    python3 assemble.py --target windows-x64
    python3 assemble.py --target macos-arm64 --zip --feedback-url URL --update-url URL

With --zip, a latest.json is written beside the zips. Publishing it and the zips in one
place, and giving --update-url that place's address (an https address, or a folder path
on a shared drive), is all that an installed copy needs in order to offer "Install and
restart" when a newer version appears.

A feedback or update URL given here is written into the launchers, so the
application built from them shows a report link and checks for newer builds.

Targets: windows-x64, macos-arm64, macos-x64, linux-x64, linux-arm64.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PYTHON_VERSION = "3.12.9"
SERIES = ".".join(PYTHON_VERSION.split(".")[:2])
APP_NAME = "Label Generator"
BUNDLE_ID = "edu.yale.library.specialcollections.labelgenerator"
USER_AGENT = "label-generator-assemble/2.0 (+Yale University Library)"

HERE = Path(__file__).resolve().parent
DESKTOP = HERE.parent
CACHE = Path(os.environ.get("LABEL_GENERATOR_BUILD_CACHE", HERE / ".cache"))

TARGETS = {
    # target          os         arch       uv python-platform triple
    "windows-x64":  ("windows", "x86_64",  "x86_64-pc-windows-msvc"),
    "macos-arm64":  ("macos",   "aarch64", "aarch64-apple-darwin"),
    "macos-x64":    ("macos",   "x86_64",  "x86_64-apple-darwin"),
    "linux-x64":    ("linux",   "x86_64",  "x86_64-unknown-linux-gnu"),
    "linux-arm64":  ("linux",   "aarch64", "aarch64-unknown-linux-gnu"),
}


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def run(command: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def host_target() -> str:
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system())
    machine = {"x86_64": "x86_64", "AMD64": "x86_64",
               "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine())
    for name, (operating_system, architecture, _) in TARGETS.items():
        if (operating_system, architecture) == (system, machine):
            return name
    return "unknown"


# --------------------------------------------------------------------- interpreter

def upstream(url: str) -> str:
    """Name the distribution at its publisher rather than at Astral's mirror.

    uv reports whichever host it prefers, and that mirror is not reachable from every
    network this is built on. The archives are the same objects published on the
    project's own GitHub releases, so the mirror is rewritten back to the source.
    """
    return url.replace("https://releases.astral.sh/github/", "https://github.com/astral-sh/")


def resolve_distribution(operating_system: str, architecture: str) -> str:
    """Ask uv where a python-build-standalone distribution lives, for any platform."""
    listing = json.loads(run(["uv", "python", "list", "--all-platforms", "--all-versions",
                              "--output-format", "json"]).stdout)
    same_version = [entry for entry in listing
                    if entry["implementation"] == "cpython" and entry["version"] == PYTHON_VERSION]
    for entry in same_version:
        if (entry["os"] == operating_system and entry["arch"] == architecture
                and entry.get("variant") in (None, "default")
                # uv offers musl first for some Linux architectures. The wheels
                # installed alongside are resolved for the gnu triple, and a musl
                # interpreter cannot load them, so the libc has to match.
                and (operating_system != "linux" or entry.get("libc") in (None, "gnu"))):
            return upstream(entry["url"])

    # uv's index drops some platforms that python-build-standalone still publishes,
    # macOS on Intel among them. Any sibling entry for the same version carries the
    # release tag, which is the only part of the URL that is not derivable.
    triple = {("macos", "x86_64"): "x86_64-apple-darwin",
              ("macos", "aarch64"): "aarch64-apple-darwin",
              ("windows", "x86_64"): "x86_64-pc-windows-msvc",
              ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
              ("linux", "aarch64"): "aarch64-unknown-linux-gnu"}.get(
                  (operating_system, architecture))
    tag = next((match.group(1) for entry in same_version
                if (match := re.search(r"/download/(\d{8})/", entry["url"]))), None)
    if triple and tag:
        derived = (f"https://github.com/astral-sh/python-build-standalone/releases/"
                   f"download/{tag}/cpython-{PYTHON_VERSION}%2B{tag}-{triple}"
                   f"-install_only_stripped.tar.gz")
        probe = urllib.request.Request(derived, method="HEAD", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(probe, timeout=60):
                say(f"uv does not index {operating_system}/{architecture}; using release {tag}")
                return derived
        except urllib.error.HTTPError as error:
            raise SystemExit(f"derived URL for {triple} answered {error.code}: {derived}")
    raise SystemExit(f"no CPython {PYTHON_VERSION} available for {operating_system}/{architecture}")


def fetch(url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    destination = CACHE / Path(url).name.replace("%2B", "+")
    if destination.exists():
        say(f"using cached {destination.name}")
        return destination
    say(f"fetching {destination.name}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def _keep(member: tarfile.TarInfo, destination: str):
    """Drop the terminal database, whose symlinks point outside the tree it ships in."""
    if "/share/terminfo" in member.name:
        return None
    return tarfile.tar_filter(member, destination)


def unpack_interpreter(archive: Path, into: Path) -> Path:
    staging = CACHE / f"unpacked-{archive.stem}"
    if not staging.exists():
        staging.mkdir(parents=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(staging, filter=_keep)
    root = staging / "python"
    if not root.is_dir():
        raise SystemExit(f"unexpected archive layout in {archive.name}")
    if into.exists():
        shutil.rmtree(into)
    shutil.copytree(root, into, symlinks=False)
    return into


# ------------------------------------------------------------------------ packages

LEAVE_BEHIND = shutil.ignore_patterns("build", "dist", "*.egg-info", "__pycache__",
                                     ".pytest_cache", ".git", ".venv", ".DS_Store", "uv.lock", "tests", "examples", "docs", "packaging")


def install_packages(site_packages: Path, triple: str) -> dict:
    """Resolve the target platform's wheels and install them as files.

    The interpreter being populated is never executed, which is what makes a Windows
    application buildable on a Mac and a macOS application buildable on Linux.

    Each local package is built from a copy rather than from the working tree, so a
    build leaves no artefacts behind in the repository and does not depend on the
    working tree being writable.
    """
    base = ["uv", "pip", "install", "--python-platform", triple,
            "--python-version", SERIES, "--target", str(site_packages), "--quiet"]

    with tempfile.TemporaryDirectory(prefix="label-generator-build-") as scratch:
        desktop = Path(scratch) / DESKTOP.name
        shutil.copytree(DESKTOP, desktop, ignore=LEAVE_BEHIND)

        say("installing the application, its dependencies and its native window toolkit")
        try:
            run([*base, f"{desktop}[window]"])
            window = "included"
        except SystemExit:
            # The browser fallback in app.py covers this; the application still runs.
            window = "unavailable for this platform; the application uses the browser"
            say(window)
            run([*base, str(desktop)])
    return {"window_toolkit": window}


#: Installed alongside, never imported: packaging tools and PyObjC's own test suite.
UNUSED_PACKAGES = {"pip", "setuptools", "pkg_resources", "wheel", "PyObjCTest"}

#: Parts of the interpreter the application never loads: the Tk toolkit and the
#: programs built on it, the bootstrap for pip, and the C headers.
UNUSED_RUNTIME = (
    "include", "tcl", "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread[0-9]*", "lib/libtcl*",
    "lib/libtk*", "DLLs/_tkinter.pyd", "DLLs/tcl*.dll", "DLLs/tk*.dll",
    *(f"{stdlib}/{name}" for stdlib in ("Lib", f"lib/python{SERIES}")
      for name in ("idlelib", "tkinter", "turtledemo", "ensurepip", "lib-dynload/_tkinter*")),
)


def prune(payload: Path, site_packages: Path) -> int:
    """Remove what an installed application cannot reach."""
    freed = 0
    interpreter_root = payload / "python"
    targets: list[Path] = []
    targets += [p for p in site_packages.glob("*/tests") if p.is_dir()]
    targets += [p for p in site_packages.glob("*.dist-info/RECORD")]
    targets += list(payload.rglob("__pycache__"))
    targets += [p for p in site_packages.iterdir() if p.is_dir() and p.name in UNUSED_PACKAGES]
    targets += [p for pattern in UNUSED_RUNTIME for p in interpreter_root.glob(pattern)]
    for path in targets:
        if not path.exists():
            continue
        freed += sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() \
            else path.stat().st_size
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    return freed


def installed_packages(site_packages: Path) -> dict:
    """Every distribution in the payload and its version, so a build says what it holds."""
    packages = {}
    for info in sorted(site_packages.glob("*.dist-info")):
        metadata = (info / "METADATA").read_text(encoding="utf-8", errors="replace")
        header = metadata.split("\n\n", 1)[0]
        fields = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
        packages[fields.get("Name", info.name)] = fields.get("Version", "unknown")
    return packages


# ------------------------------------------------------------------------ launchers

# -I isolates the bundled interpreter from any Python already on the machine: its
# environment variables and user packages are ignored.
WINDOWS_LAUNCHER = """@echo off
rem Starts the Label Generator. No installation, no administrator rights, no Python needed.
{environment}start "" "%~dp0python\\pythonw.exe" -I -m label_generator_desktop %*
"""

WINDOWS_CONSOLE_LAUNCHER = """@echo off
rem Same application, with the console left open so that any message is readable.
{environment}"%~dp0python\\python.exe" -I -m label_generator_desktop %*
echo.
pause
"""

MACOS_LAUNCHER = """#!/bin/sh
# Starts the Label Generator from inside the bundle.
here=$(cd "$(dirname "$0")" && pwd)
{environment}exec "$here/../Resources/python/bin/python{series}" -I -m label_generator_desktop "$@"
"""

LINUX_LAUNCHER = """#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
{environment}exec "$here/python/bin/python{series}" -I -m label_generator_desktop "$@"
"""

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{name}</string>
  <key>CFBundleDisplayName</key><string>{name}</string>
  <key>CFBundleExecutable</key><string>{name}</string>
  <key>CFBundleIdentifier</key><string>{bundle_id}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{version}</string>
  <key>CFBundleVersion</key><string>{version}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"""

READ_ME = """{name}

Run it
  {run_line}

Keep the application in its extracted location and use the same launcher each time.
The application carries Python and processes your collection files on this computer.
If the native window is unavailable, the interface opens in your default browser.
When an update is offered, select Install and restart and check the version in the
reopened window. Save the labels you want to keep before closing the application.
"""


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ----------------------------------------------------------------------- assembling

def launcher_environment(operating_system: str, settings: dict) -> str:
    """Lines that set the application's configuration before it starts."""
    if operating_system == "windows":
        return "".join(f'set "{name}={value}"\n' for name, value in settings.items())
    return "".join(f"export {name}={shlex.quote(value)}\n" for name, value in settings.items())


def assemble(target: str, out_root: Path, settings: dict) -> Path:
    operating_system, architecture, triple = TARGETS[target]
    say(f"target {target} ({triple})")

    url = resolve_distribution(operating_system, architecture)
    archive = fetch(url)

    staging = out_root / f"staging-{target}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    if operating_system == "macos":
        bundle = staging / f"{APP_NAME}.app"
        (bundle / "Contents" / "MacOS").mkdir(parents=True)
        (bundle / "Contents" / "Resources").mkdir(parents=True)
        payload = bundle / "Contents" / "Resources"
        top = bundle
    else:
        top = staging / APP_NAME
        top.mkdir(parents=True)
        payload = top

    interpreter_root = unpack_interpreter(archive, payload / "python")
    library = interpreter_root / ("Lib" if operating_system == "windows"
                                 else f"lib/python{SERIES}")
    site_packages = library / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    notes = install_packages(site_packages, triple)
    freed = prune(payload, site_packages)
    say(f"pruned {freed // (1 << 20)} MiB the application cannot reach")

    packages = installed_packages(site_packages)
    version = packages.get("label-generator-desktop", "unknown")
    environment = launcher_environment(operating_system, settings)

    if operating_system == "windows":
        (top / f"{APP_NAME}.bat").write_text(
            WINDOWS_LAUNCHER.format(environment=environment), encoding="utf-8", newline="\r\n")
        (top / f"{APP_NAME} (console).bat").write_text(
            WINDOWS_CONSOLE_LAUNCHER.format(environment=environment),
            encoding="utf-8", newline="\r\n")
        run_line = f'Double-click "{APP_NAME}.bat".'
        interpreter = "python/python.exe"
    elif operating_system == "macos":
        launcher = top / "Contents" / "MacOS" / APP_NAME
        launcher.write_text(MACOS_LAUNCHER.format(series=SERIES, environment=environment),
                            encoding="utf-8")
        make_executable(launcher)
        (top / "Contents" / "Info.plist").write_text(
            INFO_PLIST.format(name=APP_NAME, bundle_id=BUNDLE_ID, version=version),
            encoding="utf-8")
        run_line = f'Double-click "{APP_NAME}.app".'
        interpreter = "Contents/Resources/python/bin/python" + SERIES
    else:
        launcher = top / APP_NAME.lower().replace(" ", "-")
        launcher.write_text(LINUX_LAUNCHER.format(series=SERIES, environment=environment),
                            encoding="utf-8")
        make_executable(launcher)
        run_line = f"Run ./{launcher.name}"
        interpreter = "python/bin/python" + SERIES

    if not (payload / "python" / Path(interpreter).name).exists() \
            and not (top / interpreter).exists():
        raise SystemExit(f"no interpreter at {interpreter}")

    readme_home = top if operating_system != "macos" else staging
    (readme_home / "README.txt").write_text(
        READ_ME.format(name=APP_NAME, run_line=run_line), encoding="utf-8")

    (payload / "RUNTIME.json").write_text(json.dumps({
        "application": APP_NAME,
        "update_protocol": 1,
        "version": version,
        "target": target,
        "python": PYTHON_VERSION,
        "distribution": url,
        "distribution_sha256": digest(archive),
        "assembled": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assembled_on": host_target(),
        "assembled_from": "wheels resolved for the target; this interpreter was never executed"
                          if target != host_target() else "wheels for this host",
        "interpreter": interpreter,
        "settings": settings,
        **notes,
        "packages": packages,
    }, indent=2) + "\n", encoding="utf-8")

    say(f"assembled {sum(f.stat().st_size for f in top.rglob('*') if f.is_file()) >> 20} MiB")
    return staging


def archive_payload(staging: Path, target: str, out_root: Path) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    destination = out_root / f"label-generator-{target}.zip"
    if destination.exists():
        destination.unlink()
    say(f"packaging {destination.name}")
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(staging.rglob("*")):
            if not path.is_file() and not path.is_symlink():
                continue
            entry = zipfile.ZipInfo(str(path.relative_to(staging)))
            entry.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as handle:
                bundle.writestr(entry, handle.read())
    return destination


def write_manifest(out_root: Path, built: dict, page_url: str) -> Path:
    """Write ``latest.json`` beside the zips: the version and, for each platform, its zip.

    ``built`` maps a target to ``(zip path, version)``. Platforms already named in an
    earlier manifest of the same version are kept, so targets may be assembled one at
    a time. The application resolves each file name relative to the manifest.
    """
    version = next(iter(built.values()))[1]
    manifest = out_root / "latest.json"
    files, earlier = {}, {}
    if manifest.exists():
        earlier = json.loads(manifest.read_text(encoding="utf-8"))
        if earlier.get("version") == version:
            files = earlier.get("files", {})
    for target, (archive, _) in built.items():
        files[target] = {"name": archive.name, "sha256": digest(archive)}
    manifest.write_text(json.dumps({
        "version": version,
        "url": page_url or earlier.get("url", ""),
        "notes": "See the release notes for what changed.",
        "files": dict(sorted(files.items())),
    }, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", action="append", choices=sorted(TARGETS),
                        help="platform to assemble; repeatable, defaults to this host")
    parser.add_argument("--out", type=Path, default=DESKTOP / "dist",
                        help="where payloads and archives are written")
    parser.add_argument("--zip", action="store_true", help="also package each payload")
    parser.add_argument("--feedback-url", help="where the interface's report link points")
    parser.add_argument("--update-url", help="the release manifest the application checks")
    parser.add_argument("--page-url", default="", help="the page that lists releases, shown when a platform has no zip")
    arguments = parser.parse_args()
    settings = {name: value for name, value in (
        ("LABEL_GENERATOR_FEEDBACK_URL", arguments.feedback_url),
        ("LABEL_GENERATOR_UPDATE_URL", arguments.update_url)) if value}

    targets = arguments.target or [host_target()]
    if "unknown" in targets:
        raise SystemExit("this host is not a supported target; name one with --target")

    out_root = arguments.out.resolve()
    built = {}
    for target in targets:
        print(f"\n{APP_NAME}: {target}")
        staging = assemble(target, out_root, settings)
        if arguments.zip:
            archive = archive_payload(staging, target, out_root)
            say(f"{archive.name} is {archive.stat().st_size >> 20} MiB")
            runtime = json.loads((next(staging.rglob("RUNTIME.json"))).read_text(encoding="utf-8"))
            built[target] = (archive, runtime["version"])
    if built:
        say(f"wrote {write_manifest(out_root, built, arguments.page_url).name}")
    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
