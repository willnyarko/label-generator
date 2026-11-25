"""The in-app update: manifest files, download, checksum, unpacking, replacement."""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from label_generator.service.app import create_app
from label_generator_desktop import recovery, updates


def make_zip(path, version, *, target="linux-x64", overrides=None, omit=""):
    """Small packages in the directory layouts written by the assembler."""
    mac = target.startswith("macos")
    windows = target.startswith("windows")
    top = "Label Generator.app" if mac else "Label Generator"
    runtime = "Contents/Resources/RUNTIME.json" if mac else "RUNTIME.json"
    interpreter = ("Contents/Resources/python/bin/python3.12" if mac else
                   "python/python.exe" if windows else "python/bin/python3.12")
    launcher = "Contents/MacOS/Label Generator" if mac else "Label Generator.bat" if windows else "label-generator"
    record = dict(application="Label Generator", target=target, version=version,
                  interpreter=interpreter, update_protocol=recovery.PROTOCOL)
    record.update(overrides or {})
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(f"{top}/{runtime}", json.dumps(record))
        for name in [launcher, interpreter] + (["python/pythonw.exe"] if windows else []):
            if name != omit:
                info = zipfile.ZipInfo(f"{top}/{name}")
                info.external_attr = 0o755 << 16
                bundle.writestr(info, "fixture")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_for(folder: Path, version: str, target: str) -> Path:
    zip_path = folder / f"label-generator-{target}.zip"
    digest = make_zip(zip_path, version)
    manifest = folder / "latest.json"
    manifest.write_text(json.dumps({
        "version": version,
        "url": "https://example.invalid/releases",
        "files": {target: {"name": zip_path.name, "sha256": digest}},
    }), encoding="utf-8")
    return manifest


@pytest.mark.skipif(sys.platform == "win32", reason="The packaged Unix launchers use /bin/sh")
@pytest.mark.parametrize("platform,launcher_name,python_dir", [
    ("macos", "Label Generator.app/Contents/MacOS/Label Generator", "Label Generator.app/Contents/Resources/python/bin"),
    ("linux", "Label Generator/label-generator", "Label Generator/python/bin"),
])
def test_launcher_reads_update_folder_with_apostrophe(tmp_path, platform, launcher_name, python_dir):
    assembler = runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging" / "assemble.py"))
    folder = tmp_path / "Staff's Updates"
    folder.mkdir()
    target = f"{platform}-arm64"
    manifest = manifest_for(folder, "2.0.2", target)
    environment = assembler["launcher_environment"](platform, {"LABEL_GENERATOR_UPDATE_URL": str(manifest)})
    launcher = tmp_path / launcher_name
    launcher.parent.mkdir(parents=True)
    template = assembler[f"{platform.upper()}_LAUNCHER"]
    launcher.write_text(template.format(series=assembler["SERIES"], environment=environment), encoding="utf-8")

    # Report the path received by the bundled interpreter without opening a window.
    interpreter = tmp_path / python_dir / ("python" + assembler["SERIES"])
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/sh\nprintf "%s" "$LABEL_GENERATOR_UPDATE_URL"\n', encoding="utf-8")
    interpreter.chmod(0o755)
    received = subprocess.run(["/bin/sh", launcher], capture_output=True, text=True, check=True).stdout
    assert received == str(manifest)
    update = updates.check_for_updates("2.0.1", url=received, target=target)
    assert update is not None and update.latest == "2.0.2"


def test_a_plain_path_becomes_a_file_address(tmp_path) -> None:
    assert updates.as_location(str(tmp_path / "latest.json")).startswith("file://")
    assert updates.as_location("https://example.invalid/x.json") == "https://example.invalid/x.json"


def test_manifest_file_names_resolve_beside_the_manifest() -> None:
    info = updates.parse_manifest(
        {"version": "2.1.0", "files": {"windows-x64": {"name": "a.zip", "sha256": "AB"}}},
        "2.0.0",
        source="https://example.invalid/releases/latest/download/latest.json",
        target="windows-x64",
    )
    assert info.file_url == "https://example.invalid/releases/latest/download/a.zip"
    assert info.sha256 == "ab"


def test_a_platform_without_a_file_gets_the_page_link_instead() -> None:
    info = updates.parse_manifest(
        {"version": "2.1.0", "url": "https://example.invalid/r", "files": {}},
        "2.0.0", source="https://example.invalid/latest.json", target="windows-x64",
    )
    assert info.file_url == ""
    assert "https://example.invalid/r" in updates.describe(info)


def test_check_reads_a_manifest_from_a_folder(tmp_path) -> None:
    manifest = manifest_for(tmp_path, "9.0.0", "linux-x64")
    info = updates.check_for_updates("2.0.0", url=str(manifest), target="linux-x64")
    assert info.latest == "9.0.0"
    assert info.file_url.endswith("label-generator-linux-x64.zip")


def test_download_checks_the_checksum(tmp_path) -> None:
    manifest = manifest_for(tmp_path, "9.0.0", "linux-x64")
    info = updates.check_for_updates("2.0.0", url=str(manifest), target="linux-x64")
    updates.download(info.file_url, tmp_path / "ok.zip", expected_sha256=info.sha256)
    with pytest.raises(ValueError):
        updates.download(info.file_url, tmp_path / "bad.zip", expected_sha256="0" * 64)


def test_extract_keeps_executable_bits(tmp_path) -> None:
    archive = tmp_path / "a.zip"
    make_zip(archive, "9.0.0")
    folder = updates.extract(archive, tmp_path / "out")
    assert folder.name == "Label Generator"
    assert (folder / "label-generator").stat().st_mode & stat.S_IXUSR


def prepare(tmp_path, target="linux-x64", *, override=None, omit="", digest=None):
    archive = tmp_path / "release.zip"
    checksum = make_zip(archive, "2.1.0", target=target, overrides=override, omit=omit)
    install = recovery.Install(tmp_path / "Installed", target, "Label Generator")
    install.root.mkdir()
    saved = install.root / "staff labels.docx"
    saved.write_bytes(b"saved labels")
    called = []
    stage = tmp_path / ("build-" + "a" * 32)
    info = updates.UpdateInfo("2.0.0", "2.1.0", "", file_url=archive.as_uri(),
                              sha256=checksum if digest is None else digest)
    updater = updates.Updater(info, install, stage=stage, on_ready=lambda: called.append(True))
    updater.start()
    updater._thread.join(timeout=10)
    assert saved.read_bytes() == b"saved labels"
    return updater, called


@pytest.mark.parametrize("target", ["macos-arm64", "macos-x64", "windows-x64", "linux-x64"])
def test_verified_update_is_staged_away_from_the_working_install(tmp_path, target, monkeypatch):
    # Cross-platform ZIP fixtures have stand-in interpreters. The launch check is exercised separately.
    probes = []
    monkeypatch.setattr(updates, "verify_runtime", lambda path, version: probes.append((path, version)))
    updater, called = prepare(tmp_path, target)
    assert called and updater.status()["state"] == "restarting"
    assert (updater.stage / "version").read_text() == "2.1.0"
    interpreter = updater.install.package(updater.stage).check("2.1.0")
    assert probes == [(interpreter, "2.1.0")]
    assert not (tmp_path / "active").exists()


@pytest.mark.parametrize("options", [
    {"digest": ""}, {"digest": "12"}, {"digest": "0" * 64},
    {"override": {"application": "Other"}}, {"override": {"target": "macos-x64"}},
    {"override": {"version": "2.0.0"}}, {"override": {"update_protocol": None}},
    {"omit": "label-generator"}, {"omit": "python/bin/python3.12"},
    {"target": "windows-x64", "omit": "python/pythonw.exe"},
])
def test_unverified_update_keeps_app_running_and_can_be_retried(tmp_path, options):
    updater, called = prepare(tmp_path, **options)
    assert updater.status()["state"] == "error"
    assert not called and not updater.stage.exists()
    updater.start()
    updater._thread.join(timeout=10)
    assert updater.status()["state"] == "error"
    assert not called and not updater.stage.exists()


@pytest.mark.parametrize("returncode,reported", [(1, b""), (0, b"2.0.0"), (0, b"2.1.0")])
def test_staged_interpreter_must_report_promised_version(monkeypatch, returncode, reported):
    def run(command, **opts):
        assert command[:3] == ["interpreter", "-I", "-c"]
        assert opts["timeout"] > 0
        return subprocess.CompletedProcess(command, returncode, reported)
    monkeypatch.setattr(subprocess, "run", run)
    if reported == b"2.1.0":
        updates.verify_runtime(Path("interpreter"), "2.1.0")
    else:
        with pytest.raises(ValueError):
            updates.verify_runtime(Path("interpreter"), "2.1.0")


def test_interrupted_download_can_retry_from_same_running_app(tmp_path, monkeypatch):
    from io import BytesIO
    archive = tmp_path / "update.zip"
    digest = make_zip(archive, "2.1.0")
    class Interrupted(BytesIO):
        def read(self, size):
            if self.tell():
                raise ConnectionError("connection closed")
            return super().read(16)
    streams = iter([Interrupted(archive.read_bytes()), BytesIO(archive.read_bytes())])
    install = recovery.Install(tmp_path / "original", "linux-x64", "Label Generator")
    install.root.mkdir()
    saved = install.root / "saved.docx"
    saved.write_bytes(b"original")
    staged = tmp_path / "stage"
    ready = []
    info = updates.UpdateInfo("2.0", "2.1.0", "", file_url=archive.as_uri(), sha256=digest)
    updater = updates.Updater(info, install, stage=staged, on_ready=lambda: ready.append(True),
                              opener=lambda *args, **kwargs: next(streams))
    monkeypatch.setattr(updates, "verify_runtime", lambda *args: None)
    updater.start()
    updater._thread.join(5)
    assert not ready and not staged.exists() and updater.status()["state"] == "error"
    updater.start()
    updater._thread.join(5)
    assert ready == [True] and saved.read_bytes() == b"original"


@pytest.mark.parametrize("outcome", ["opens", "crashes", "hangs", "wrong version", "cannot launch", "commit fails"])
def test_confirmed_version_survives_an_unsuccessful_upgrade(tmp_path, monkeypatch, outcome):
    # Start from a previously accepted update, so rollback must choose that version.
    install = recovery.Install(tmp_path / "Installed", "linux-x64", "Label Generator")
    previous = "build-" + "b" * 32
    recovery.write_marker(tmp_path / "active", previous)
    archive = tmp_path / "new.zip"
    make_zip(archive, "3.0.0")
    launched = []
    def launch(package, args, env):
        launched.append(package.root)
        script = "pass"
        if len(launched) == 1:
            staged = Path(env[recovery.STAGE])
            updates.extract(archive, staged)
            recovery.write_marker(staged / "version", "3.0.0")
            script = f"raise SystemExit({recovery.RESTART})"
        elif recovery.READY in env:
            if outcome == "cannot launch":
                raise OSError("Cannot launch the candidate")
            if outcome == "opens" or outcome == "commit fails" or outcome == "wrong version":
                version = "2.9.0" if outcome == "wrong version" else "3.0.0"
                script = f"from pathlib import Path; Path({env[recovery.READY]!r}).write_text({version!r}); import time; time.sleep(.4)"
            elif outcome == "hangs":
                script = "import time; time.sleep(30)"
            else:
                script = "raise SystemExit(1)"
        else:
            assert env[recovery.RESTORED] == "1"
        return subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE)
    monkeypatch.setattr(recovery, "launch", launch)
    original = recovery.write_marker
    def write(path, value):
        if outcome == "commit fails" and path.name == "active":
            raise OSError("Could not commit the update")
        original(path, value)
    monkeypatch.setattr(recovery, "write_marker", write)
    assert recovery.run_versions(install, tmp_path, [], True, previous, timeout=.7) == 0
    active = recovery.read_slot(tmp_path / "active")
    if outcome == "opens":
        assert launched == [install.package(tmp_path / previous).root, install.package(tmp_path / active).root]
        assert active != previous and recovery.read_slot(tmp_path / "previous") == previous
    else:
        assert active == previous
        assert len(launched) == 3 and launched[0] == launched[2] and launched[0] != launched[1]


def test_next_launch_after_interruption_uses_last_confirmed_version(tmp_path, monkeypatch):
    base = recovery.Install(tmp_path / "Installed", "linux-x64", "Label Generator")
    active = "build-" + "b" * 32
    interrupted = "build-" + "c" * 32
    (tmp_path / interrupted).mkdir()
    recovery.write_marker(tmp_path / "active", active)
    recovery.write_marker(tmp_path / "trial", interrupted)
    def launch(package, args, env):
        assert package == base.package(tmp_path / active)
        assert env[recovery.RESTORED] == "1" and recovery.READY not in env
        return subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.PIPE)
    monkeypatch.setattr(recovery, "launch", launch)
    assert recovery.supervise(base, tmp_path, []) == 0
    assert not (tmp_path / interrupted).exists()
    assert recovery.read_slot(tmp_path / "active") == active


def test_interruption_after_commit_keeps_the_confirmed_version(tmp_path, monkeypatch):
    base = recovery.Install(tmp_path / "Installed", "linux-x64", "Label Generator")
    accepted = "build-" + "d" * 32
    previous = "build-" + "e" * 32
    (tmp_path / previous).mkdir()
    for name, value in [("previous", previous), ("trial", accepted), ("active", accepted)]:
        recovery.write_marker(tmp_path / name, value)

    def launch(package, args, env):
        assert package == base.package(tmp_path / accepted)
        assert recovery.RESTORED not in env
        return subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.PIPE)

    monkeypatch.setattr(recovery, "launch", launch)
    assert recovery.supervise(base, tmp_path, []) == 0
    assert (tmp_path / previous).is_dir()
    assert recovery.read_slot(tmp_path / "active") == accepted


def test_another_open_instance_cannot_apply_or_clean_an_update(tmp_path, monkeypatch):
    base = recovery.Install(tmp_path / "Installed", "linux-x64", "Label Generator")
    downloading = tmp_path / ("build-" + "f" * 32)
    downloading.mkdir()
    def launch(package, args, env):
        assert package == base and recovery.STAGE not in env
        return subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.PIPE)
    monkeypatch.setattr(recovery, "launch", launch)
    with recovery.try_lock(tmp_path / "manager.lock") as held:
        assert held and recovery.supervise(base, tmp_path, ["--version"]) == 0
        assert downloading.is_dir()


def test_service_health_alone_cannot_confirm_a_trial():
    calls = []
    with TestClient(create_app(on_opened=lambda: calls.append(1))) as client:
        assert client.get("/health").is_success
        assert client.get("/api/config").json()["confirm_open"]
        assert calls == []
        assert client.post("/api/update/opened").is_success
        assert client.post("/api/update/opened").is_success
        assert calls == [1]
        assert not client.get("/api/config").json()["confirm_open"]


def test_a_copy_run_from_source_is_never_updated_in_place(monkeypatch) -> None:
    monkeypatch.setenv(recovery.STAGE, "unused")
    monkeypatch.setattr(updates, "find_install", lambda: None)
    info = updates.UpdateInfo("2.0.0", "9.0.0", "", file_url="file:///x.zip")
    assert updates.make_updater(info) is None


def test_the_service_offers_the_update_only_when_there_is_an_updater() -> None:
    class Fake:
        def status(self):
            return {"state": "available", "message": "", "version": "9.0.0"}

        def start(self):
            return {"state": "working", "message": "Downloading", "version": "9.0.0"}

    with TestClient(create_app(updater=Fake(), notice="Version 9.0.0 is available.")) as client:
        assert client.get("/api/config").json()["update"] is True
        assert client.get("/api/update").json()["state"] == "available"
        assert client.post("/api/update").json()["state"] == "working"
    with TestClient(create_app()) as client:
        assert client.get("/api/config").json()["update"] is False
        assert client.post("/api/update").status_code == 404
