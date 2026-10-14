"""Route each box to the label stock that fits its container.

Currently, boxes come in three physical shapes:

- the full Hollinger or Paige box
- the half Hollinger box
- the tall flat box

Yale uses Avery sheets for labels, and each shape uses a different sheet as set in ``config/box_kinds.toml``.
The physical shape determines which Avery sheet is used and what the output file name would be. `auto` picks
the shape from the container type which will have been recorded for the box in
ArchivesSpace; there is also the option to choose one shape for all, and then staff can
decide whether or not to edit on those.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from typing import Optional

from content import CONFIG
from models.lrr import BoxLRR
from projections.options import BoxKind, BoxKindChoice

CONFIG_FILE = CONFIG / "box_kinds.toml"


@dataclass(frozen=True)
class Stock:
    sheet: str
    suffix: str
    vertical: bool
    container_types: tuple[str, ...] = field(default=())
    container_type_starts: Optional[str] = None
    taller_than_inches: float = 0.0


def _load() -> dict[BoxKind, Stock]:
    table = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        kind: Stock(**{**entry, "container_types": tuple(entry.get("container_types", ()))})
        for kind, entry in table.items()
    }


STOCKS: dict[BoxKind, Stock] = _load()


def classify_box_kind(container_type: Optional[str]) -> BoxKind:
    text = (container_type or "").lower().strip()
    kinds = list(STOCKS)
    for kind in kinds[1:]:
        stock = STOCKS[kind]
        if text in stock.container_types:
            return kind
        if stock.container_type_starts and text.startswith(stock.container_type_starts):
            if _height_inches(text) > stock.taller_than_inches:
                return kind
    return kinds[0]


def _height_inches(container_type: str) -> float:
    match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)h\b", container_type)
    return float(match.group(1)) if match else 0.0


def group_boxes_by_kind(
    boxes: list[BoxLRR], *, choice: BoxKindChoice = "auto"
) -> dict[BoxKind, list[BoxLRR]]:
    if choice != "auto":
        return {choice: list(boxes)}
    groups: dict[BoxKind, list[BoxLRR]] = {kind: [] for kind in STOCKS}
    for box in boxes:
        groups[classify_box_kind(box.container_type)].append(box)
    return {kind: group for kind, group in groups.items() if group}
