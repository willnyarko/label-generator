"""Read any supported input into one YCAR record."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from label_generator.engine.models.ycar import YcarRecord
from label_generator.engine.readers.detect import detect_input_kind
from label_generator.engine.readers.ead import read_ead
from label_generator.engine.readers.sheet import read_sheet
from label_generator.engine.repositories import by_code


def read_input(
    path: Path,
    *,
    collection: Optional[str] = None,
    call_number: Optional[str] = None,
    repository: Optional[str] = None,
    header_rows: Optional[int] = None,
    input_kind: Optional[str] = None,
) -> YcarRecord:
    """Read an EAD or a bulk import spreadsheet into a YCAR record.

    ``collection``, ``call_number`` and ``repository`` (a short name from
    ``config/repositories.json``) are what a user has supplied. They replace what
    the reader found, for every kind of input, so a bad EAD export can be
    corrected as well as a file that doesn't state its collection identity.
    """
    kind = input_kind or detect_input_kind(path)
    record = read_ead(path) if kind == "ead" else read_sheet(path, kind, header_rows=header_rows)
    record.apply_identity(collection=collection, call_number=call_number, repository=by_code(repository))
    return record
