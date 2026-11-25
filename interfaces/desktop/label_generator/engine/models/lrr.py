"""LRR, the label-ready record, holds everything one printed label needs.
It is where reading a source ends and writing labels begins.

A YCAR record is derived into one LRR row per folder label and one per box label, and the Word and CSV writers read only these rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

MISSING_BOX_SENTINEL = "10001"

NumberingScheme = Literal["through-collection", "per-box"]


@dataclass
class FolderLRR:
    """One label's worth of folder facts.

    ``ancestors`` runs outermost first and is as long as the component is deep
    (see ``MAX_COMPONENT_DEPTH``); the labels print the first as a series line.
    """

    collection: str
    call_number: str
    box: str
    folder: Optional[str]
    container_type: Optional[str]
    ancestors: list[str] = field(default_factory=list)
    folder_title: str = ""
    folder_dates: str = ""
    # A physical folder can appear under more than one top-level component.
    aggregate_numbers: set[int] = field(default_factory=set)
    placeholder_box: bool = False

    @property
    def series(self) -> str:
        """The top-level series the folder belongs to, or an empty string."""
        return self.ancestors[0] if self.ancestors else ""

    def to_row(self, depth: int = 1) -> dict[str, Any]:
        """One CSV row, with ``depth`` ancestor columns so every row has the same columns."""
        return {
            "COLLECTION": self.collection,
            "CALL_NO.": self.call_number,
            "BOX": self.box,
            "FOLDER": self.folder,
            "CONTAINER_TYPE": self.container_type,
            **_numbered("C{:02d}_ANCESTOR", self.ancestors, depth),
            "FOLDER TITLE": self.folder_title,
            "FOLDER DATES": self.folder_dates,
        }


@dataclass
class BoxLRR:
    """One box label. ``all_series`` lists the distinct top-level series in the box."""

    repository: str
    collection: str
    call_number: str
    box: str
    folder_count: Optional[str]
    first_folder: Optional[str] = None
    last_folder: Optional[str] = None
    container_type: Optional[str] = None
    all_series: list[str] = field(default_factory=list)
    placeholder_box: bool = False

    @property
    def series(self) -> str:
        """The series a box label prints: the first one found in the box."""
        return self.all_series[0] if self.all_series else ""

    def to_row(self, width: int = 1) -> dict[str, Any]:
        """One CSV row, with ``width`` series columns."""
        return {
            "REPOSITORY": self.repository,
            "COLLECTION": self.collection,
            "CALL_NO.": self.call_number,
            "BOX": self.box,
            "FOLDER_COUNT": self.folder_count,
            "FIRST_FOLDER": self.first_folder,
            "LAST_FOLDER": self.last_folder,
            "CONTAINER_TYPE": self.container_type,
            **_numbered("SERIES_{}", self.all_series, width),
        }


def _numbered(pattern: str, values: list[str], width: int) -> dict[str, Optional[str]]:
    """``{pattern.format(n): value}`` for n = 1..width, padding with None."""
    padded = values + [None] * (width - len(values))
    return {pattern.format(n): v for n, v in enumerate(padded[:width], start=1)}


@dataclass
class LrrBundle:
    """Everything a run prints: the folder rows, the box rows, and how the folders are numbered."""
    folders: list[FolderLRR] = field(default_factory=list)
    boxes: list[BoxLRR] = field(default_factory=list)
    stated_scheme: Optional[NumberingScheme] = None  # the scheme the source's own folder numbers show
    numbering: NumberingScheme = "per-box"  # the scheme the folders are numbered by
    stated_folders: int = 0  # folders whose number the source states
    # Menu order is source order. None groups the leaves directly under the resource.
    aggregates: list[Optional[str]] = field(default_factory=list)
    # The CSV columns for ancestors and series, sized to the whole collection, so a run
    # for part of it writes the same columns as a run for all of it.
    ancestor_columns: int = 1
    series_columns: int = 1

    def folders_as_dicts(self) -> list[dict[str, Any]]:
        """The folder rows as CSV rows with one shared set of columns."""
        return [f.to_row(self.ancestor_columns) for f in self.folders]

    def boxes_as_dicts(self) -> list[dict[str, Any]]:
        """The box rows as CSV rows with one shared set of columns."""
        return [b.to_row(self.series_columns) for b in self.boxes]
