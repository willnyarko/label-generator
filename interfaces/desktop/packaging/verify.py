#!/usr/bin/env python3
"""Check an assembled payload, and say plainly what each check does and does not show.

Two kinds of evidence, kept apart. Structural checks read the payload and hold for
every target: the interpreter is there, the packages are there, and the compiled
extension modules are the target platform's binaries rather than this machine's.
They establish nothing about behaviour. The live check starts the application and
drives it over HTTP, and can only run on a payload built for this host.

    python3 verify.py --payload <dist>/staging-windows-x64 --target windows-x64
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SERIES = "3.12"
APP_NAME = "Label Generator"
HERE = Path(__file__).resolve().parent

MAGIC = {
    "windows": (b"MZ",),
    "macos": (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"),
    "linux": (b"\x7fELF",),
}
EXTENSION = {"windows": ".pyd", "macos": ".so", "linux": ".so"}

MACH_O_CPU = {0x0100000C: "aarch64", 0x01000007: "x86_64"}
PE_MACHINE = {0x8664: "x86_64", 0xAA64: "aarch64"}
ELF_MACHINE = {0x3E: "x86_64", 0xB7: "aarch64"}


def architectures_of(module: Path, operating_system: str) -> set:
    """Read the CPU architectures out of a compiled extension module's own header.

    Shipping an Intel build to an Apple Silicon machine is a mistake a platform
    check alone does not catch, so the header is read rather than the file name.
    A macOS wheel is often universal, carrying both architectures in one file, so
    this answers with a set rather than a single name.
    """
    raw = module.read_bytes()
    if operating_system == "macos":
        if raw[:4] in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):  # universal
            count = int.from_bytes(raw[4:8], "big")
            return {MACH_O_CPU.get(int.from_bytes(raw[8 + 20 * i:12 + 20 * i], "big"), "unknown")
                    for i in range(count)}
        return {MACH_O_CPU.get(int.from_bytes(raw[4:8], "little"), "unknown")}
    if operating_system == "windows":
        offset = int.from_bytes(raw[0x3C:0x40], "little")
        if raw[offset:offset + 4] != b"PE\x00\x00":
            return {"unknown"}
        return {PE_MACHINE.get(int.from_bytes(raw[offset + 4:offset + 6], "little"), "unknown")}
    return {ELF_MACHINE.get(int.from_bytes(raw[18:20], "little"), "unknown")}

failures: list[str] = []
notes: list[str] = []


def check(condition: bool, description: str) -> bool:
    print(f"  {'ok  ' if condition else 'FAIL'}  {description}")
    if not condition:
        failures.append(description)
    return condition


def locate(payload: Path, operating_system: str) -> tuple[Path, Path]:
    """Return the interpreter and its site-packages inside a payload."""
    if operating_system == "macos":
        root = next(payload.glob("*.app")) / "Contents" / "Resources" / "python"
        return root / f"bin/python{SERIES}", root / f"lib/python{SERIES}/site-packages"
    root = next(payload.glob(APP_NAME)) / "python"
    if operating_system == "windows":
        return root / "python.exe", root / "Lib" / "site-packages"
    return root / f"bin/python{SERIES}", root / f"lib/python{SERIES}/site-packages"


def structural(payload: Path, target: str, operating_system: str) -> None:
    print(f"\nStructure of {payload.name}")
    interpreter, site_packages = locate(payload, operating_system)

    check(interpreter.exists(), f"interpreter present at {interpreter.name}")
    check((site_packages.parent / "threading.py").is_file(), "interpreter includes its threading module")
    check((site_packages / "label_generator").is_dir(), "label-making code installed")
    check((site_packages / "label_generator_desktop").is_dir(), "desktop window code installed")
    interface = site_packages / "label_generator" / "service" / "static" / "index.html"
    check(interface.is_file(), "the browser interface asset is installed")

    # The point of a cross-assembled payload: the compiled wheels are the target's.
    suffix = EXTENSION[operating_system]
    extensions = [p for p in (site_packages / "lxml").glob(f"*{suffix}")] if \
        (site_packages / "lxml").is_dir() else []
    if check(bool(extensions), f"lxml carries compiled extension modules ({suffix})"):
        wrong = []
        for module in extensions:
            with module.open("rb") as handle:
                head = handle.read(4)
            if not any(head.startswith(magic) for magic in MAGIC[operating_system]):
                wrong.append(module.name)
        check(not wrong, f"those modules are {operating_system} binaries, not this host's")
        wanted = target.split("-", 1)[1].replace("arm64", "aarch64").replace("x64", "x86_64")
        seen = set()
        for module in extensions:
            seen |= architectures_of(module, operating_system)
        check(wanted in seen, f"carries {wanted} code (headers say {', '.join(sorted(seen))})")

    launcher = {
        "windows": payload / APP_NAME / f"{APP_NAME}.bat",
        "macos": payload / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME,
        "linux": payload / APP_NAME / "label-generator",
    }[operating_system]
    check(launcher.exists(), f"launcher present ({launcher.name})")
    if operating_system != "windows":
        check(launcher.stat().st_mode & 0o111 != 0, "launcher is executable")
    if operating_system == "macos":
        check((payload / f"{APP_NAME}.app" / "Contents" / "Info.plist").is_file(),
              "bundle carries Info.plist")

    record = next(payload.rglob("RUNTIME.json"), None)
    if check(record is not None, "RUNTIME.json records what this payload is"):
        recorded = json.loads(record.read_text())
        check(recorded.get("target") == target, f"records its target as {target}")
        check(recorded.get("update_protocol") == 1, "declares desktop update recovery support")
        check((site_packages / "label_generator_desktop/recovery.py").is_file(), "recovery launcher installed")
        notes.append(f"window toolkit: {recorded.get('window_toolkit')}")

    # A payload that names the machine it was built on is not relocatable.
    build_path = str(payload.resolve())
    leaked = [p.name for p in site_packages.rglob("*.pth")
              if build_path in p.read_text(errors="replace")]
    check(not leaked, "no build-host paths written into the payload")
    editable = [p.name for p in site_packages.glob("__editable__*")]
    check(not editable, "every package is installed as files, none as a link to a build directory")


LIVE = r'''
import io, json, sys, urllib.request, urllib.error, uuid
from pathlib import Path
from label_generator_desktop.service_host import ServiceHost
from label_generator.service.app import render_interface

inputs = Path(sys.argv[1])
host = ServiceHost(port=None)
base = host.start()
result = {"base": base}

def post(path, fields, files=()):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for name, value in fields.items():
        if value is None: continue
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    for name, filename, payload in files:
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n".encode())
        body.write(b"Content-Type: application/octet-stream\r\n\r\n" + payload + b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(base + path, data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())

try:
    with urllib.request.urlopen(base + "/health", timeout=30) as response:
        result["health"] = response.status
    with urllib.request.urlopen(base + "/", timeout=30) as response:
        served = response.read()
    result["interface_matches_asset"] = (served == render_interface().encode("utf-8") and b"{{" not in served)

    ead = inputs / "example-ead3.xml"
    analysis = post("/api/analyze", {}, [("file", ead.name, ead.read_bytes())])
    result["ead_collection"] = analysis["summary"]["collection"]

    generated = json.loads(urllib.request.urlopen(urllib.request.Request(
        base + "/api/generate", data=json.dumps({"token": analysis["token"],
            "formats": ["html", "excel", "word", "csv"]}).encode(),
        headers={"Content-Type": "application/json"}), timeout=300).read())
    result["generated"] = [f["name"] for f in generated["files"]]

    sheet = inputs / "example-yale.csv"
    spreadsheet = post("/api/analyze", {}, [("file", sheet.name, sheet.read_bytes())])
    result["spreadsheet_identity"] = {k: v for k, v in spreadsheet["summary"].items()
        if "collection" in k or "call" in k or "provenance" in k or "confirm" in k}
finally:
    host.stop()

print("RESULT " + json.dumps(result, default=str))
'''


def live(payload: Path, operating_system: str, inputs: Path) -> None:
    print("\nBehaviour (this host only)")
    interpreter, _ = locate(payload, operating_system)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(LIVE)
        program = handle.name
    finished = subprocess.run([str(interpreter), program, str(inputs)],
                              capture_output=True, text=True, timeout=900)
    payload_line = next((line for line in finished.stdout.splitlines()
                         if line.startswith("RESULT ")), None)
    if not payload_line:
        print(finished.stdout[-2000:]); print(finished.stderr[-3000:])
        check(False, "the application started and answered")
        return
    observed = json.loads(payload_line[len("RESULT "):])
    check(observed.get("health") == 200, "the service starts and reports healthy")
    check(observed.get("interface_matches_asset") is True,
          "the interface matches the rendered installed page, including its wording")
    check(bool(observed.get("ead_collection")),
          f"an EAD finding aid is read (collection: {observed.get('ead_collection')})")
    generated_types = {Path(name).suffix for name in observed.get("generated", [])}
    check(generated_types == {".docx", ".csv", ".html", ".xlsx"},
          f"labels generate in every format ({len(observed.get('generated') or [])} files)")
    identity = observed.get("spreadsheet_identity") or {}
    check(bool(identity), f"a spreadsheet reports its collection identity {identity}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--inputs", type=Path, help="sample inputs (default: the bundled examples)",
                        default=HERE.parent / "examples")
    parser.add_argument("--live", action="store_true",
                        help="also start the application; only valid for this host's target")
    arguments = parser.parse_args()

    operating_system = arguments.target.split("-")[0]

    structural(arguments.payload, arguments.target, operating_system)
    if arguments.live:
        live(arguments.payload, operating_system, arguments.inputs)

    for note in notes:
        print(f"\n  note: {note}")
    if failures:
        print(f"\n{len(failures)} check(s) failed")
        return 1
    print("\nall checks passed")
    if not arguments.live:
        print("Structural only. This says the payload is put together correctly and carries\n"
              "the target's binaries. It says nothing about whether it runs; only that\n"
              "platform can show that.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
