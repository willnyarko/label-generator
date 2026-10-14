"""Read any supported input into one YCAR record."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from models.ycar import YcarRecord
from readers.detect import detect_input_kind
from readers.ead import read_ead
from readers.sheet import read_sheet
from repositories import by_code


def read_input(
    path: Path,
    *,
    collection: Optional[str] = None,
    call_number: Optional[str] = None,
    repository: Optional[str] = None,
) -> YcarRecord:
    kind = detect_input_kind(path)
    record = read_ead(path) if kind == "ead" else read_sheet(path, kind)
    record.apply_identity(collection=collection, call_number=call_number, repository=by_code(repository))
    return record
