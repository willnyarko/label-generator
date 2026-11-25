"""Which kind of input a file is: an EAD, or one of the two bulk import spreadsheet layouts."""

from __future__ import annotations

import csv
import io
import stat
from pathlib import Path
from typing import Optional

from label_generator.engine.content import say
from label_generator.engine.notices import InputError
from label_generator.engine.readers.columns import find_header
from lxml import etree

# An ArchivesSpace note can be longer than csv.reader's default 128 KiB field
# limit, even in a column the labels do not use. This value fits Windows too.
csv.field_size_limit(2**31 - 1)

#: The file types the tool takes: EAD exports and bulk import spreadsheets.
SUPPORTED_SUFFIXES = {".xml", ".csv"}


def preflight(path: Path) -> None:
    """Refuse an input that cannot be processed at all."""
    try:
        mode = path.stat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        raise InputError("not-a-file", path=path) from None
    except OSError as exc:
        raise InputError("cannot-open", path=path.name, reason=exc.strerror or str(exc)) from exc
    if not stat.S_ISREG(mode):
        raise InputError("not-a-file", variant="folder" if stat.S_ISDIR(mode) else None, path=path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        excel = path.suffix.lower() in {".xlsx", ".xls", ".xlsm", ".xlsb"}
        raise InputError("wrong-file-type", variant="excel" if excel else None)
    try:
        with path.open("rb") as handle:
            first_byte = handle.read(1)
    except OSError as exc:
        raise InputError("cannot-open", path=path.name, reason=exc.strerror or exc) from exc
    if not first_byte:
        # Left alone, an empty file fails later as "no labelable rows", which
        # sends staff looking for missing containers in a file with no content.
        raise InputError("empty-file", path=path.name)


def decode_csv(raw: bytes) -> str:
    """The text of a CSV file in whichever encoding it was saved in.

    "CSV UTF-8" is tried first, then cp1252, which Windows writes for plain
    "CSV (Comma delimited)" and which holds accents UTF-8 cannot read. Latin-1
    reads any byte, so a file always decodes.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def csv_rows(path: Path) -> list[list[str]]:
    """Every row of a CSV file as a list of cells."""
    return list(csv.reader(io.StringIO(decode_csv(path.read_bytes()), newline="")))


def spreadsheet_layout(text: str) -> Optional[str]:
    """The bulk import layout a CSV's header rows name (``yale-csv`` or ``native-csv``), or None."""
    from itertools import islice
    header = find_header(list(islice(csv.reader(io.StringIO(text, newline="")), 3)))
    return header.kind if header else None


def detect_input_kind(path: Path) -> str:
    """Name the kind of input (``ead``, ``yale-csv`` or ``native-csv``) or raise the error that explains why it is none."""
    preflight(path)  # leaves only .xml and .csv
    if path.suffix.lower() == ".csv":
        # Read complete records. A wide template can exceed the old 8 KiB prefix.
        from itertools import islice
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                with path.open(encoding=encoding, newline="") as handle:
                    header = find_header(list(islice(csv.reader(handle), 3)))
                break
            except UnicodeDecodeError:
                continue
        layout = header.kind if header else None
        if layout is None:
            raise InputError("not-bulk-import", name=path.name)
        return layout
    try:
        with path.open("rb") as handle:
            root = next(etree.iterparse(handle, events=("start",), recover=True), (None, None))[1]
    except etree.XMLSyntaxError:
        return "ead"  # Let the full reader supply the parser reason and location.
    if root is None or etree.QName(root).localname == "ead":
        return "ead"  # The reader reports malformed XML with the parser detail.
    raise InputError("unreadable-ead", name=path.name, reason=say("ead_reason.not_ead", line=root.sourceline))


def recognised_kind(path: Path) -> Optional[str]:
    """The kind of input a file is, or None; it never raises, so a list of likely inputs can ask it of every file."""
    try:
        return detect_input_kind(path)
    except (InputError, OSError):
        return None
