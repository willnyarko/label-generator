"""Read label fields from current Yale-custom, native and legacy single-header CSVs."""

from __future__ import annotations

from pathlib import Path

from label_generator.engine.models.ycar import Container, DateValue, Extent, Identifier, Repository, Title, YcarComponent, YcarRecord
from label_generator.engine.notices import InputError
from label_generator.engine.readers.columns import find_header
from label_generator.engine.readers.detect import csv_rows
from label_generator.engine.repositories import by_code, from_uri


def _date(row: dict[str, str]) -> str:
    if row.get("date"):
        return row["date"]
    dates = []
    for end in ("begin", "end"):
        value = row.get(end) or "-".join(row[key] for unit in ("year", "month", "day")
                                         if row.get(key := f"{unit}_{end}"))
        if value and value not in dates:
            dates.append(value)
    return "–".join(dates)


def read_sheet(path: Path, kind: str, *, header_rows: int | None = None) -> YcarRecord:
    table = csv_rows(path)
    header = find_header(table[:3], header_rows)
    if header is None:
        raise InputError("not-bulk-import", name=path.name)
    record = YcarRecord()
    stack: list[YcarComponent] = []
    for cells in table[header.count:]:
        row = {key: v.strip() for key, v in zip(header.columns, cells) if key and v.strip()}
        if row.get("collection") and not record.titles:
            record.titles.append(Title(row["collection"], kind="unittitle"))
            record.title_provenance = "declared"
        if row.get("call_number") and not record.identifiers:
            record.identifiers.append(Identifier("call-number", row["call_number"]))
            record.call_number_provenance = "declared"
        if record.repository is None:
            repo = from_uri(row.get("uri", "")) or by_code(row.get("repo_code"))
            if row.get("repository"):
                repo = Repository(repo.code if repo else "", row["repository"])
            if repo:
                record.repository, record.repository_provenance = repo, "declared"

        date = _date(row)
        level = row.get("level", "").lower()
        if row.get("depth") == "0" and not level:
            if date and stack:
                stack[-1].dates.append(DateValue("inclusive", date))
            continue
        if not (date or any(row.get(k) for k in ("level", "title", "box", "folder", "extent", "unitid", "series_no"))):
            continue
        comp = YcarComponent(level=level or "file", unitid=row.get("series_no") or row.get("unitid"))
        if row.get("title"):
            comp.title = Title(row["title"])
        if date:
            comp.dates.append(DateValue("inclusive", date))
        if row.get("box"):
            top_type = row.get("box_type", "").lower()
            comp.containers.append(Container("folder" if top_type == "folder" else "box", row["box"],
                                             (row.get("profile") or top_type).lower() or None))
        if row.get("folder"):
            comp.containers.append(Container("folder", row["folder"], row.get("folder_type", "").lower() or None))
        if row.get("extent") and row["extent"] != "0":
            comp.extents.append(Extent(kind="extent", quantity=row["extent"], unit=row.get("extent_unit", "")))
        try:
            depth = max(1, int(row.get("depth", "")))
        except ValueError:
            # Without a depth column, only an explicitly described aggregate can
            # parent another row. Ordinary rows in a reduced sheet are peers.
            if level in {"series", "recordgrp", "fonds", "collection", "class"}:
                depth = 1
            else:
                while stack and stack[-1].level not in {"series", "subseries", "recordgrp", "fonds", "collection", "class"}:
                    stack.pop()
                if level == "subseries" and stack and stack[-1].level == "subseries":
                    stack.pop()
                depth = len(stack) + 1
        del stack[depth - 1:]
        (stack[-1].children if stack else record.components).append(comp)
        stack.append(comp)
    return record
