"""Bulk-import spreadsheet reader: Yale's custom CSV and ArchivesSpace's native CSV.

The two layouts hold more or less the same facts about a collection, albeit under different headers. Therefore we use a single reader to serve both. Each layout is only a table of header names (``YALE``, ``NATIVE``). A sheet describes the components of a collection or resource. Because the tool takes neither the collection name nor the call number from a sheet, a user will have to type in these values during the run, or if they skip, be notified about it at the end of the run. The tool derives the name of the repository from the resource URI when a row from the spreadsheet has one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from models.ycar import Container, DateValue, Extent, Title, YcarComponent, YcarRecord
from readers.detect import csv_rows
from repositories import from_uri


@dataclass(frozen=True)
class Layout:
    kind: str
    header_row: int
    resource_uri: str
    title: str
    level: str
    depth: str
    unitid: str
    date: str
    box: str
    box_type: tuple[str, ...]
    folder: str
    folder_type: tuple[str, ...]
    extent_number: str
    extent_unit: str


YALE = Layout(
    kind="yale-csv",
    header_row=0,
    resource_uri="resource uri",
    title="title",
    level="level type",
    depth="level number",
    unitid="unitid",
    date="date expression",
    box="container 1 value / BOX by default",
    box_type=("container profile", "container 1 type"),
    folder="container 2 value / FOLDER by default",
    folder_type=("container 2 type",),
    extent_number="extent number",
    extent_unit="extent value",
)

NATIVE = Layout(
    kind="native-csv",
    header_row=1,
    resource_uri="Resource URI (either this or EAD ID is *REQUIRED*)",
    title="Title (either or Date is *REQUIRED*)",
    level="Description Level *REQUIRED*",
    depth="Hierarchical Relationship *REQUIRED*",
    unitid="Component Unique Identifier",
    date="Date(1) expression",
    box="Top Container [indicator]",
    box_type=("Top Container type",),
    folder="Child indicator",
    folder_type=("Child type",),
    extent_number="Extent number *REQUIRED* if specifying Extent",
    extent_unit="Extent type: cubic feet, cds, etc.*REQUIRED* if specifying Extent",
)

LAYOUTS = {layout.kind: layout for layout in (YALE, NATIVE)}


def read_sheet(path: Path, kind: str) -> YcarRecord:
    lay = LAYOUTS[kind]
    table = csv_rows(path)
    names = [name.strip() for name in table[lay.header_row]] if len(table) > lay.header_row else []
    rows = [
        {name: cell.strip() for name, cell in zip(names, raw, strict=False) if name}
        for raw in table[lay.header_row + 1 :]
    ]

    record = YcarRecord()
    stack: list[YcarComponent] = []

    for row in rows:
        level = row.get(lay.level, "").lower()
        if not (level or row.get(lay.box) or row.get(lay.title)):
            continue

        comp = YcarComponent(level=level or "file", unitid=row.get(lay.unitid) or None)
        if row.get(lay.title):
            comp.title = Title(display=row[lay.title])
        if row.get(lay.date):
            comp.dates.append(DateValue(type="inclusive", display=row[lay.date]))
        if row.get(lay.box):
            comp.containers.append(Container(kind="box", indicator=row[lay.box], type=_first(row, lay.box_type)))
        if row.get(lay.folder):
            comp.containers.append(Container(kind="folder", indicator=row[lay.folder], type=_first(row, lay.folder_type)))
        count = row.get(lay.extent_number, "")
        if count and count != "0":
            comp.extents.append(Extent(kind="extent", quantity=count, unit=row.get(lay.extent_unit, "")))

        try:
            depth = max(int(row.get(lay.depth, "")), 1)
        except ValueError:
            depth = 1 if level == "series" or not stack else 2
        del stack[depth - 1 :]
        (stack[-1].children if stack else record.components).append(comp)
        stack.append(comp)

    _repository_from_uri(record, rows, lay)
    return record


def _first(row: dict[str, str], columns: tuple[str, ...]) -> Optional[str]:
    return next((row[c].lower() for c in columns if row.get(c)), None)


def _repository_from_uri(record: YcarRecord, rows: list[dict[str, str]], lay: Layout) -> None:
    for row in rows:
        repository = from_uri(row.get(lay.resource_uri, ""))
        if repository:
            record.repository, record.repository_provenance = repository, "declared"
            break
