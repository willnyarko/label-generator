"""The lines of text that make up a label, as the Word writer prints them."""

from __future__ import annotations

from content import say
from models.lrr import BoxLRR, FolderLRR


def box_heading(row: BoxLRR) -> str:
    return say("labels.box_heading", box=row.box)


def box_folder_line(row: FolderLRR) -> str:
    return say("labels.box_and_folder", box=row.box, folder=row.folder or "")


def ancestor_chain(row: FolderLRR) -> str:
    return " / ".join(filter(None, row.ancestors[1:]))


def box_range_text(row: BoxLRR) -> str:
    if row.first_folder and row.last_folder:
        return say("labels.folder_range", first=row.first_folder, last=row.last_folder)
    if row.first_folder:
        return say("labels.folder_single", first=row.first_folder)
    return row.folder_count or ""
