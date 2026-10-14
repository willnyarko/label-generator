"""Which kind of input a file is: an EAD, or one of the two bulk import spreadsheet layouts."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

from content import say
from notices import InputError

HEAD_BYTES = 8192

SUPPORTED_SUFFIXES = {".xml", ".csv"}


def preflight(path: Path) -> None:
    if not path.is_file():
        raise InputError("not-a-file", path=path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise InputError("wrong-file-type", name=path.name)
    try:
        with path.open("rb") as handle:
            first_byte = handle.read(1)
    except OSError as exc:
        raise InputError("cannot-open", path=path, reason=exc.strerror or exc) from exc
    if not first_byte:
        raise InputError("empty-file", path=path)


def decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def csv_rows(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(decode_csv(path.read_bytes()), newline="")))


def spreadsheet_layout(text: str) -> Optional[str]:
    lines = text.lower().splitlines()
    first = lines[0] if lines else ""
    second = lines[1].lstrip('"') if len(lines) > 1 else ""
    if "archivesspace field code" in first or second.startswith("field name"):
        return "native-csv"
    if "resource uri" in first or "container 1 value" in first:
        return "yale-csv"
    return None


def detect_input_kind(path: Path) -> str:
    preflight(path)
    with path.open("rb") as handle:
        head = handle.read(HEAD_BYTES)
    if path.suffix.lower() == ".csv":
        layout = spreadsheet_layout(decode_csv(head))
        if layout is None:
            raise InputError("not-bulk-import", name=path.name)
        return layout
    if b"<ead" in head.lower():
        return "ead"
    raise InputError("unreadable-ead", name=path.name, reason=say("ead_reason.not_ead"))


def recognised_kind(path: Path) -> Optional[str]:
    try:
        return detect_input_kind(path)
    except (InputError, OSError):
        return None
