"""Presentation choices every output projection (Word, HTML, Excel) accepts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from ..engine.models.lrr import BoxLRR
from ..engine.projections.options import BoxKindChoice, FolderLayout
BoxFormat = Literal["default", "half-hollinger", "flat"]
BoxFormatChoice = Literal["auto", "default", "half-hollinger", "flat"]  # "auto" routes box by box
BoxFolderText = Literal["show", "omit"]


@dataclass(frozen=True)
class RenderOptions:
    """The choices a person makes about how labels are laid out; every surface passes one of these."""
    folder_layout: FolderLayout = "regular"
    box_format: BoxFormatChoice = "auto"
    box_folder_text: BoxFolderText = "show"


def stock_kind(choice: BoxFormatChoice) -> BoxKindChoice:
    """Translate the displayed box format to its sheet stock."""
    return "full" if choice == "default" else choice


def without_folder_details(boxes: list[BoxLRR]) -> list[BoxLRR]:
    return [replace(box, folder_count=None, first_folder=None, last_folder=None) for box in boxes]


DEFAULT_RENDER_OPTIONS = RenderOptions()
