"""Derive label-ready folder and box records (LRR) from a YCAR record.

Each terminal (or "leaf") component, that is, a c or cNN component of an EAD's <dsc>
(or a component row of a spreadsheet) with no component beneath it, yields one folder
row per physical folder it names. When no folder is stated, it yields one row per
folder its extent counts, or one row when its extent counts none. A leaf with no box
number takes box 10001. The rows are then ordered, numbered and de-duplicated, and
each box the leaves name gets a box row, filled in from the folders it holds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from content import say
from lrr.numbering import apply_numbering, stated_scheme
from models.lrr import MISSING_BOX_SENTINEL, BoxLRR, FolderLRR, LrrBundle, NumberingScheme
from models.ycar import Container, YcarComponent, YcarRecord


@dataclass(frozen=True)
class _BoxSource:
    box: str
    container_type: Optional[str]
    series: str


def derive_lrr(
    record: YcarRecord,
    *,
    numbering_preference: Optional[NumberingScheme] = None,
    first_folder: int = 1,
) -> LrrBundle:
    bundle = LrrBundle()
    collection = record.primary_title()
    call_number = record.call_number()
    repository = record.repository_display()
    box_sources: list[_BoxSource] = []

    for ancestors, terminal in record.terminal_components():
        ancestor_values = _project_ancestors(ancestors)
        box_sources.append(
            _BoxSource(
                box=_box_number(terminal.containers),
                container_type=_container_type(terminal),
                series=ancestor_values[0] if ancestor_values else "",
            )
        )
        bundle.folders.extend(_folder_rows(terminal, collection, call_number, ancestor_values))
        for path in [tuple(ancestor_values[:depth]) for depth in range(1, len(ancestor_values) + 1)] or [()]:
            if path not in bundle.aggregates:
                bundle.aggregates.append(path)

    bundle.folders.sort(key=_sort_key)
    bundle.stated_scheme = stated_scheme(bundle.folders)
    bundle.numbering = bundle.stated_scheme or numbering_preference or "per-box"
    stated = {id(row) for row in bundle.folders if row.folder}
    apply_numbering(bundle.folders, bundle.numbering, first_folder)
    bundle.folders.sort(key=_sort_key)
    bundle.folders = _one_label_per_folder(bundle.folders)
    bundle.stated_folders = sum(id(row) in stated for row in bundle.folders)
    bundle.boxes = _build_boxes(
        box_sources,
        bundle.folders,
        repository=repository,
        collection=collection,
        call_number=call_number,
        through_collection=bundle.numbering == "through-collection",
    )
    bundle.ancestor_columns = max((len(row.ancestors) for row in bundle.folders), default=1) or 1
    bundle.series_columns = max((len(box.all_series) for box in bundle.boxes), default=1) or 1

    return bundle


def box_key(raw: str) -> str:
    return str(raw or "").replace("Box ", "").strip()


def _build_boxes(
    sources: list[_BoxSource],
    folders: list[FolderLRR],
    *,
    repository: str,
    collection: str,
    call_number: str,
    through_collection: bool,
) -> list[BoxLRR]:
    sources_by_box: dict[str, list[_BoxSource]] = {}
    for source in sorted(sources, key=lambda source: _natural(source.box)):
        sources_by_box.setdefault(box_key(source.box), []).append(source)
    folders_by_box: dict[str, list[FolderLRR]] = {}
    for row in folders:
        folders_by_box.setdefault(box_key(row.box), []).append(row)

    boxes: list[BoxLRR] = []
    for key, source_rows in sources_by_box.items():
        rows = folders_by_box.get(key, [])
        first, last = _folder_span(rows) if through_collection else (None, None)
        series = [row.series for row in rows if row.series] or [s.series for s in source_rows if s.series]
        boxes.append(
            BoxLRR(
                repository=repository,
                collection=collection,
                call_number=call_number,
                box=key,
                folder_count=_folder_count_text(len(rows)),
                first_folder=first,
                last_folder=last,
                container_type=source_rows[0].container_type,
                all_series=list(dict.fromkeys(series)),
            )
        )
    return boxes


def _folder_count_text(count: int) -> Optional[str]:
    if not count:
        return None
    if count == 1:
        return say("labels.folder_count_one", count=count)
    return say("labels.folder_count_many", count=count)


def _folder_span(rows: list[FolderLRR]) -> tuple[Optional[str], Optional[str]]:
    leading = [re.match(r"\d+", str(row.folder or "").strip()) for row in rows]
    if not leading or not all(leading):
        return None, None
    numbers = [int(match.group()) for match in leading]
    low, high = min(numbers), max(numbers)
    return str(low), str(high) if high != low else None


def _natural(raw) -> tuple:
    text = str(raw or "").strip()
    match = re.search(r"\d+", text)
    return (int(match.group()) if match else 0, text.lower())


def _one_label_per_folder(rows: list[FolderLRR]) -> list[FolderLRR]:
    seen: set[tuple[str, str]] = set()
    kept: list[FolderLRR] = []
    for row in rows:
        key = (box_key(row.box), str(row.folder or "").strip())
        if key[1] and key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _box_number(containers: list[Container]) -> str:
    for c in containers:
        if c.kind == "box" and c.indicator:
            return c.indicator
    for c in containers:
        if c.kind != "folder" and c.indicator:
            return c.indicator
    return MISSING_BOX_SENTINEL


def _folder_date(comp: YcarComponent) -> str:
    if comp.dates:
        return comp.dates[0].display
    return say("labels.date_unavailable")


def _infer_folder_count(comp: YcarComponent) -> Optional[int]:
    for ext in comp.extents:
        if ext.quantity and ext.quantity.isdigit() and "folder" in (ext.unit or "").lower() and int(ext.quantity) > 0:
            return int(ext.quantity)
        match = re.search(r"(?<![\d.])(\d+)\s+folders?\b", ext.display or "", re.IGNORECASE)
        if match and int(match.group(1)) > 0:
            return int(match.group(1))
    return None


def _folder_rows(
    terminal: YcarComponent,
    collection: str,
    call_number: str,
    ancestor_values: list[str],
) -> list[FolderLRR]:
    declared = next((c for c in terminal.containers if c.kind == "folder"), None)
    if declared:
        folders: list[Optional[str]] = _declared_folders(declared.indicator.strip())
    else:
        folders = [None] * (_infer_folder_count(terminal) or 1)

    title = terminal.title_display()
    return [
        FolderLRR(
            collection=collection,
            call_number=call_number,
            box=_box_number(terminal.containers),
            folder=folder,
            container_type=_container_type(terminal),
            ancestors=ancestor_values,
            folder_title=title
            if len(folders) == 1
            else say("labels.folder_part", title=title, number=n, total=len(folders)),
            folder_dates=_folder_date(terminal),
        )
        for n, folder in enumerate(folders, 1)
    ]


def _declared_folders(text: str) -> list[str]:
    match = re.fullmatch(r"(?:folder\s*)?(\d+)\s*-\s*(?:folder\s*)?(\d+)", text, flags=re.IGNORECASE)
    if match:
        first, last = (int(n) for n in match.groups())
        if last >= first:
            return [str(n) for n in range(first, last + 1)]
    return [text]


def _roman(n: int) -> str:
    numerals = ""
    for value, numeral in (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ):
        count, n = divmod(n, value)
        numerals += numeral * count
    return numerals


def _project_ancestors(ancestors: list[YcarComponent]) -> list[str]:
    return [_ancestor_title(ancestor) for ancestor in ancestors]


def _ancestor_title(component: YcarComponent) -> str:
    title = component.title_display()
    numbered = re.match(r"series\s+([0-9]+|[ivxlcdm]+)\b", title, flags=re.IGNORECASE)
    if (component.level or "").lower() != "series" or not component.unitid or numbered:
        return title
    number = re.sub(r"^series\s+", "", component.unitid.strip(), flags=re.IGNORECASE)
    if number.isdigit() and int(number) > 0:
        number = _roman(int(number))
    lead = say("labels.series", number=number)
    return f"{lead}{' ' if lead.endswith('.') else '. '}{title}"


def _container_type(component: YcarComponent) -> Optional[str]:
    return component.containers[0].type if component.containers else None


def _sort_key(row: FolderLRR) -> tuple:
    return (*_natural(row.box), *_natural(row.folder))
