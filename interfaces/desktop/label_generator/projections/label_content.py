"""Shared label text helpers for projections."""

from __future__ import annotations

from ..content import say
from ..engine.models.lrr import BoxLRR, FolderLRR
from .options import BoxFolderText


def box_heading(row: BoxLRR) -> str:
    """The line that names the box on its label."""
    return say("labels.box_heading", box=row.box)


def box_folder_line(row: FolderLRR) -> str:
    """The line that gives a folder label its box and folder number."""
    return say("labels.box_and_folder", box=row.box, folder=row.folder or "")


def ancestor_chain(row: FolderLRR) -> str:
    """Every ancestor below the series line, joined into one run of text."""
    return " / ".join(filter(None, row.ancestors[1:]))


def box_range_text(row: BoxLRR, *, display: BoxFolderText = "show") -> str:
    """The folders a box holds, as a range, a single folder or a count; empty when ``display`` is ``omit``."""
    if display == "omit":
        return ""
    if row.first_folder and row.last_folder:
        return say("labels.folder_range", first=row.first_folder, last=row.last_folder)
    if row.first_folder:
        return say("labels.folder_single", first=row.first_folder)
    return row.folder_count or ""
