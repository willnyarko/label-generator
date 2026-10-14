"""The layout choices a user makes: writers follow these choices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FolderLayout = Literal["regular", "left"]
BoxKind = Literal["full", "half-hollinger", "flat"]
BoxKindChoice = Literal["auto", "full", "half-hollinger", "flat"]


@dataclass(frozen=True)
class RenderOptions:
    folder_layout: FolderLayout = "regular"
    box_kind: BoxKindChoice = "auto"
    box_folders: bool = True


DEFAULT_RENDER_OPTIONS = RenderOptions()
