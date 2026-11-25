"""Publish the Word sheets and CSVs together, including when a rerun replaces files."""

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from models.lrr import LrrBundle
from projections.options import RenderOptions
from projections.rows import write_rows
from projections.word import write_word_outputs


@contextmanager
def _publication_lock():
    # Runs may render concurrently. Serialize replacement and rollback for a
    # run. A single lock serves every output directory without leaving lock
    # files beside the labels. The OS releases it when the process terminates.
    lock_path = Path(tempfile.gettempdir()) / "label-generator-publication.lock"
    with lock_path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def write_outputs(bundle: LrrBundle, directory: Path, stem: str, options: RenderOptions) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory, prefix=".label-generator-") as staging:
        stage = Path(staging)
        files = write_word_outputs(bundle, stage, stem, options=options)
        files += write_rows(bundle, stage, stem)
        backup = stage / "previous"
        backup.mkdir()
        with _publication_lock():
            published = []
            try:
                for file in files:
                    target = directory / file.name
                    if target.exists():
                        shutil.copy2(target, backup / file.name)
                    file.replace(target)
                    published.append(target)
            except OSError:
                # A Word file may still be open. Restore any earlier files from
                # this run before reporting the failure.
                for target in reversed(published):
                    previous = backup / target.name
                    if previous.exists():
                        previous.replace(target)
                    else:
                        target.unlink()
                raise
    return published
