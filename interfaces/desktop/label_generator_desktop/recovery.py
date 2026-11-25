"""Keep the installed launcher usable while a new desktop version proves it can open."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid


# These values are shared by the installed launcher and subsequent desktop releases.
PROTOCOL = 1
RESTART = 73
STAGE = "LABEL_GENERATOR_UPDATE_STAGE"
READY = "LABEL_GENERATOR_UPDATE_READY"
RESTORED = "LABEL_GENERATOR_UPDATE_RESTORED"
SUPERVISED = "LABEL_GENERATOR_SUPERVISED"
OPEN_TIMEOUT = 90
_SLOT = re.compile(r"build-[0-9a-f]{32}")


@dataclass(frozen=True)
class Install:
    root: Path
    target: str
    application: str

    @property
    def runtime(self) -> Path:
        payload = self.root / "Contents/Resources" if self.target.startswith("macos") else self.root
        return payload / "RUNTIME.json"

    def package(self, slot: Path) -> Install:
        name = self.application + (".app" if self.target.startswith("macos") else "")
        return Install(slot / name, self.target, self.application)

    def interpreter(self, record: dict) -> Path:
        relative = Path(record["interpreter"])
        if relative.anchor or ".." in relative.parts:
            raise ValueError("Invalid interpreter location")
        return self.root / relative

    def check(self, version: str) -> Path:
        record = json.loads(self.runtime.read_text(encoding="utf-8"))
        expected = {"application": self.application, "target": self.target,
                    "version": version, "update_protocol": PROTOCOL}
        if not isinstance(record, dict) or any(record.get(k) != v for k, v in expected.items()):
            raise ValueError("Incompatible application, platform, version or update protocol")
        settings = record.get("settings", {})
        if not isinstance(settings, dict) or not all(isinstance(v, str) for v in settings.values()):
            raise ValueError("Invalid launcher settings")
        interpreter = self.interpreter(record)
        if self.target.startswith("windows"):
            files = [self.root / (self.application + ".bat"), interpreter, interpreter.with_name("pythonw.exe")]
        elif self.target.startswith("macos"):
            files = [self.root / "Contents/MacOS" / self.application, interpreter]
        else:
            files = [self.root / self.application.lower().replace(" ", "-"), interpreter]
        if not all(p.is_file() and (self.target.startswith("windows") or os.access(p, os.X_OK))
                   for p in files):
            raise ValueError("The launcher or its interpreter is missing or unusable")
        return interpreter


def find_install() -> Install | None:
    for folder in Path(sys.executable).resolve().parents:
        marker = folder / "RUNTIME.json"
        if marker.is_file():
            try:
                record = json.loads(marker.read_text(encoding="utf-8"))
                target, name = record["target"], record["application"]
                if not isinstance(target, str) or not isinstance(name, str) or not name or Path(name).name != name:
                    return None
                root = folder.parent.parent if target.startswith("macos") else folder
                return Install(root, target, name)
            except (OSError, ValueError, TypeError, KeyError):
                return None
    return None


def storage(install: Install) -> Path:
    if sys.platform == "win32":
        parent = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        parent = Path.home() / "Library/Application Support"
    else:
        parent = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    identity = os.path.normcase(str(install.root.resolve())).encode()
    return parent / "Label Generator" / "updates" / hashlib.sha256(identity).hexdigest()[:24]


@contextmanager
def try_lock(path: Path):
    """A process-scoped lock. The OS releases it even on abrupt termination."""
    with path.open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            yield False
        else:
            yield True


def read_slot(path: Path) -> str:
    try:
        name = path.read_text(encoding="ascii").strip()
    except (FileNotFoundError, UnicodeError):
        return ""
    return name if _SLOT.fullmatch(name) else ""


def write_marker(path: Path, value: str) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        # Preserve the rename across a power loss on filesystems supporting directory fsync.
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass


def collect(store: Path, retained: set[str], own_session: Path) -> None:
    # Other open instances may still need an earlier version's files.
    for lease in store.glob("session-*.lock"):
        if lease != own_session:
            with try_lock(lease) as unused:
                if not unused:
                    return
            with suppress(OSError):
                lease.unlink(missing_ok=True)
    for slot in store.glob("build-*"):
        if slot.name not in retained and _SLOT.fullmatch(slot.name):
            shutil.rmtree(slot, ignore_errors=True)


def launch(install: Install, args: list[str], env: dict):
    record = json.loads(install.runtime.read_text(encoding="utf-8"))
    interpreter = install.interpreter(record)
    if sys.platform == "win32" and Path(sys.executable).name.lower() == "pythonw.exe":
        interpreter = interpreter.with_name("pythonw.exe")
    for key in ("LABEL_GENERATOR_UPDATE_URL", "LABEL_GENERATOR_FEEDBACK_URL"):
        if value := record.get("settings", {}).get(key):
            env[key] = value
    command = [str(interpreter), "-I", "-m", "label_generator_desktop.recovery", *args]
    return subprocess.Popen(command, env=env, stdin=subprocess.PIPE)


def watch_launcher() -> None:
    """Close an orphaned UI if the owning launcher disappears during an update."""
    if os.environ.get(SUPERVISED) and sys.stdin is not None:
        def watch():
            os.read(sys.stdin.fileno(), 1)  # EOF when the launcher exits, including forced exits
            os._exit(1)
        threading.Thread(target=watch, name="desktop-launcher-watch", daemon=True).start()


def opened(process: subprocess.Popen, marker: Path, version: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        if marker.exists():
            return marker.read_text(encoding="utf-8") == version and process.poll() is None
        time.sleep(0.1)
    return False


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def try_version(base: Install, store: Path, stage: Path, active: str, args: list[str],
                env: dict, timeout: float) -> subprocess.Popen | None:
    """The active pointer is the commit. Every failure before it leaves the old copy in place."""
    process = None
    try:
        candidate = base.package(stage)
        version = (stage / "version").read_text(encoding="utf-8")
        candidate.check(version)
        write_marker(store / "trial", stage.name)
        process = launch(candidate, args, {**env, READY: str(stage / "ready")})
        if not opened(process, stage / "ready", version, timeout):
            raise ValueError("Updated interface did not open")
        write_marker(store / "previous", active)
        write_marker(store / "active", stage.name)
        return process
    except (OSError, ValueError, KeyError, TypeError):
        if process is not None:
            stop(process)
            process.stdin.close()
        shutil.rmtree(stage, ignore_errors=True)
        return None


def run_versions(base: Install, store: Path, args: list[str], writer: bool, active: str,
                 *, timeout: float = OPEN_TIMEOUT) -> int:
    trial = None
    interrupted = read_slot(store / "trial") if writer else ""
    restored = bool(interrupted and interrupted != active)
    while True:
        stage = store / ("build-" + uuid.uuid4().hex)
        env = os.environ.copy()
        for key in (STAGE, READY, RESTORED):
            env.pop(key, None)
        env[SUPERVISED] = "1"
        if writer:
            env[STAGE] = str(stage)
        if trial:
            process = try_version(base, store, trial, active, args, env, timeout)
            if process is None:
                restored = True
                trial = None
                continue
            active = trial.name
        else:
            if restored:
                env[RESTORED] = "1"
            current = base.package(store / active) if active else base
            try:
                process = launch(current, args, env)
            except (OSError, ValueError, TypeError, KeyError):
                if not active:
                    raise
                previous = read_slot(store / "previous")
                active = previous if previous != active else ""
                if writer:
                    write_marker(store / "active", active)
                restored = True
                continue
        if writer and not any(a in ("--version", "--help", "-h") for a in args):
            with suppress(OSError):
                (store / "trial").unlink(missing_ok=True)
        try:
            result = process.wait()
        finally:
            process.stdin.close()
        if not writer or result != RESTART or not (stage / "version").is_file():
            return result
        restored = False
        trial = stage


def supervise(base: Install, store: Path, args: list[str]) -> int:
    session = store / ("session-" + uuid.uuid4().hex + ".lock")
    with ExitStack() as locks:
        try:
            store.mkdir(mode=0o700, parents=True, exist_ok=True)
            registered = locks.enter_context(try_lock(session))
            writer = registered and locks.enter_context(try_lock(store / "manager.lock"))
        except OSError:
            writer = False  # A read-only profile can still open its working version.
        try:
            active = read_slot(store / "active")
        except PermissionError:
            active = ""
        try:
            if writer:
                with suppress(OSError):
                    collect(store, {active, read_slot(store / "previous")}, session)
            return run_versions(base, store, args, writer, active)
        finally:
            locks.close()
            with suppress(OSError):
                session.unlink(missing_ok=True)


def main() -> int:
    base = find_install()
    if base:
        return supervise(base, storage(base), sys.argv[1:])
    from .app import main as run_app
    return run_app()


if __name__ == "__main__":
    # The launcher starts this worker with the selected version's own interpreter.
    watch_launcher()
    from .app import main as run_app
    raise SystemExit(run_app())
