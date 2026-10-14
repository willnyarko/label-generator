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
    collection: str
    call_number: str
    box: str
    folder: Optional[str]
    container_type: Optional[str]
    ancestors: list[str] = field(default_factory=list)
    folder_title: str = ""
    folder_dates: str = ""

    @property
    def series(self) -> str:
        return self.ancestors[0] if self.ancestors else ""

    def to_row(self, depth: int = 1) -> dict[str, Any]:
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
    repository: str
    collection: str
    call_number: str
    box: str
    folder_count: Optional[str]
    first_folder: Optional[str] = None
    last_folder: Optional[str] = None
    container_type: Optional[str] = None
    all_series: list[str] = field(default_factory=list)

    @property
    def series(self) -> str:
        return self.all_series[0] if self.all_series else ""

    def to_row(self, width: int = 1) -> dict[str, Any]:
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
    padded = values + [None] * (width - len(values))
    return {pattern.format(n): v for n, v in enumerate(padded[:width], start=1)}


@dataclass
class LrrBundle:
    folders: list[FolderLRR] = field(default_factory=list)
    boxes: list[BoxLRR] = field(default_factory=list)
    stated_scheme: Optional[NumberingScheme] = None
    numbering: NumberingScheme = "per-box"
    stated_folders: int = 0
    aggregates: list[tuple[str, ...]] = field(default_factory=list)
    ancestor_columns: int = 1
    series_columns: int = 1

    def folders_as_dicts(self) -> list[dict[str, Any]]:
        return [f.to_row(self.ancestor_columns) for f in self.folders]

    def boxes_as_dicts(self) -> list[dict[str, Any]]:
        return [b.to_row(self.series_columns) for b in self.boxes]
