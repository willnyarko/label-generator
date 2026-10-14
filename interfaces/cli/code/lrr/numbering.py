"""Number the folders of a collection the way the institution numbers them.

Folder numbering typically follows one of two schemes:
(1) where numbering starts at 1 and then continues throughout the entire collection, (``through-collection``) and
(2) where numbering starts again at 1 in each box (``per-box``).

The former is an older Beinecke (and potentially, other repository) practice, whereas
the latter is more modern. By default, folder numbering defaults to whichever scheme is inherent in the input source file.
Otherwise, the user chooses, and the ``per-box`` scheme applies by default.
"""

from __future__ import annotations

import re
from typing import Optional

from models.lrr import FolderLRR, NumberingScheme


def stated_scheme(folders: list[FolderLRR]) -> Optional[NumberingScheme]:
    boxes_by_number = _stated_numbers(folders)
    if len(set().union(*boxes_by_number.values())) < 2:
        return None
    repeated = any(len(boxes) > 1 for boxes in boxes_by_number.values())
    return "per-box" if repeated else "through-collection"


def apply_numbering(folders: list[FolderLRR], scheme: NumberingScheme, first_folder: int = 1) -> None:
    for row in folders:
        if row.folder:
            row.folder = _normalize_declared_folder(row.folder)
    per_box = scheme == "per-box"
    highest: dict[str, int] = {}
    for number, boxes in _stated_numbers(folders).items():
        for box in boxes if per_box else [""]:
            highest[box] = max(highest.get(box, 0), number)
    if not per_box:
        highest.setdefault("", first_folder - 1)
    for row in folders:
        if not row.folder:
            scope = row.box if per_box else ""
            highest[scope] = highest.get(scope, 0) + 1
            row.folder = str(highest[scope])


def _stated_numbers(folders: list[FolderLRR]) -> dict[int, set[str]]:
    found: dict[int, set[str]] = {}
    for row in folders:
        match = re.match(r"\d+", _normalize_declared_folder(row.folder or ""))
        if match:
            found.setdefault(int(match.group()), set()).add(row.box)
    return found


def _normalize_declared_folder(raw: str) -> str:
    return re.sub(r"^folder\s+", "", str(raw).strip(), flags=re.IGNORECASE)
