"""The layout choices a user makes: writers follow these choices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FolderLayout = Literal["regular", "left"]
BoxKind = Literal["full", "half-hollinger", "flat"]
BoxKindChoice = Literal["auto", "full", "half-hollinger", "flat"]  # "auto" decides box by box


@dataclass(frozen=True)
class RenderOptions:
    """Left and right folder labels or left only, which kind of box the box labels are for, and whether they show folders."""
    folder_layout: FolderLayout = "regular"
    box_kind: BoxKindChoice = "auto"
    box_folders: bool = True  # box labels show the folders a box holds, as a range or a count


DEFAULT_RENDER_OPTIONS = RenderOptions()
