"""Choose which part of a collection to print labels for: all of it, chosen boxes or chosen aggregates.

A collection is always read and numbered whole first (see ``lrr/derive.py``), and a
selection then keeps part of its rows. A box label describes the whole box, so a box
is printed in full whenever any of its folders is chosen, and every label reads the
same as it does in a run for the whole collection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal, Optional

from label_generator.engine.lrr.derive import box_key
from label_generator.engine.models.lrr import LrrBundle

Scope = Literal["all", "boxes", "aggregates"]


@dataclass(frozen=True)
class Selection:
    """The part of a collection a run prints, and the answer the person typed to choose it."""

    scope: Scope = "all"
    boxes: tuple[str, ...] = ()
    aggregates: tuple[int, ...] = ()
    typed: str = ""

    @property
    def suffix(self) -> str:
        """What a run's file names add after the collection, such as "_boxes_12-15"; empty for the whole collection."""
        if self.scope == "all":
            return ""
        words = re.sub(r"\s*,\s*", "_", self.typed.strip())
        return f"_{self.scope}_" + re.sub(r"[^A-Za-z0-9_-]", "", words)

    def apply(self, bundle: LrrBundle) -> LrrBundle:
        """The rows this selection keeps; the whole bundle for the whole collection."""
        if self.scope == "all":
            return bundle
        if self.scope == "boxes":
            chosen = set(self.boxes)
            folders = [row for row in bundle.folders if box_key(row.box) in chosen]
        else:
            groups = set(self.aggregates)
            folders = [row for row in bundle.folders if groups.intersection(row.aggregate_numbers)]
            box_keys = {(box_key(row.box), row.placeholder_box) for row in folders}
            return replace(bundle, folders=folders, boxes=[box for box in bundle.boxes if (box.box, box.placeholder_box) in box_keys])
        return replace(bundle, folders=folders, boxes=[box for box in bundle.boxes if box.box in chosen])


def read_boxes(typed: str, boxes: list[str]) -> Optional[tuple[str, ...]]:
    """The boxes a typed answer names, in shelf order; None when any part of it names no box.

    "12-15" is boxes 12 to 15 in shelf order, with any 12A between them, and
    "3, 7-9" combines single boxes and ranges. "Box 12" is read as 12.
    """
    position = {box.lower(): i for i, box in enumerate(boxes)}
    chosen: set[int] = set()
    for part in typed.split(","):
        part = _without_box_word(part)
        if not part:
            continue
        if part in position:
            chosen.add(position[part])
            continue
        ends = [_without_box_word(end) for end in part.split("-")]
        if len(ends) != 2 or ends[0] not in position or ends[1] not in position:
            return None
        first, last = sorted((position[ends[0]], position[ends[1]]))
        chosen.update(range(first, last + 1))
    return tuple(boxes[i] for i in sorted(chosen)) or None


def read_numbers(typed: str, count: int) -> Optional[tuple[int, ...]]:
    """The list numbers from 1 to ``count`` that "2", "3-5" or "1, 4-6" names; None when any part is out of range."""
    chosen: set[int] = set()
    for part in typed.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not match:
            return None
        first, last = sorted((int(match.group(1)), int(match.group(2) or match.group(1))))
        if first < 1 or last > count:
            return None
        chosen.update(range(first, last + 1))
    return tuple(sorted(chosen)) or None


def _without_box_word(text: str) -> str:
    """A typed box number in lower case, without a leading "Box "."""
    return re.sub(r"^box\s+", "", text.strip(), flags=re.IGNORECASE).lower()
