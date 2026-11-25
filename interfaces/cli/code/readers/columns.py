"""Column codes and display labels used by the two import sheets and older Yale CSVs."""

from dataclasses import dataclass

# The first spelling is the field code. Display labels and old spellings follow.
YALE = {
    "collection": ("collection_name", "Collection name"),
    "call_number": ("call_number", "Call number"),
    "repository": ("repository",),
    "repo_code": ("repo_code", "Repository code"),
    "uri": ("resource uri",),
    "depth": ("depth", "Level number"),
    "level": ("level", "Level type"),
    "series_no": ("series_no", "Series Number"),
    "unitid": ("source_unitid", "Source component unit identifier", "unitid"),
    "title": ("title",),
    "date": ("date_expr", "Date expression"),
    "year_begin": ("year_begin", "Year begin"), "year_end": ("year_end", "Year end"),
    "month_begin": ("month_begin", "Month begin"), "month_end": ("month_end", "Month end"),
    "day_begin": ("day_begin", "Day begin"), "day_end": ("day_end", "Day end"),
    "box": ("top_ind", "Box (numbers only)", "container 1 value / BOX by default"),
    "folder": ("child_ind", "Folder (numbers only)", "container 2 value / FOLDER by default"),
    "box_type": ("top_type", "Top container type", "container 1 type"),
    "folder_type": ("child_type", "Child container type", "container 2 type"),
    "profile": ("container profile",),
    "extent": ("extent_no", "Extent number"),
    "extent_unit": ("extent_unit", "Extent unit", "extent value"),
}
NATIVE = {
    "call_number": ("collection_id", "Call number"),
    "uri": ("res_uri", "Resource URI (either this or EAD ID is *REQUIRED*)"),
    "depth": ("hierarchy", "Hierarchical Relationship *REQUIRED*"),
    "level": ("level", "Description Level *REQUIRED*"),
    "title": ("title", "Title (either or Date is *REQUIRED*)"),
    "unitid": ("unit_id", "Component Unique Identifier"),
    "date": ("expression", "Date(1) expression"),
    "begin": ("begin", "Date(1) Begin"), "end": ("end", "Date(1) end"),
    "box": ("indicator_1", "Top Container [indicator]"),
    "folder": ("indicator_2", "Child indicator"),
    "box_type": ("type_1", "Top Container type"),
    "folder_type": ("type_2", "Child type"),
    "extent": ("number", "Extent number *REQUIRED* if specifying Extent"),
    "extent_unit": ("extent_type", "Extent type: cubic feet, cds, etc.*REQUIRED* if specifying Extent"),
}


def _key(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _aliases(fields):
    return {_key(alias): name for name, aliases in fields.items() for alias in aliases}


_YALE = _aliases(YALE)
_NATIVE = _aliases(NATIVE)


@dataclass(frozen=True)
class Header:
    kind: str
    columns: tuple[str | None, ...]
    count: int


def find_header(rows: list[list[str]], header_rows: int | None = None) -> Header | None:
    """Use field codes first. A second display row may rename them; older sheets use names alone."""
    if not rows:
        return None
    first = [_key(v) for v in rows[0]]
    if {"collection", "call_no.", "box", "container_type"} <= set(first):
        return None  # The generator's own output CSVs also have a repository column.
    second = [_key(v) for v in rows[1]] if len(rows) > 1 else []
    native_marker = any(v.startswith("archivesspace field code") or v == "field name" for v in first)
    native = native_marker or any(v in _NATIVE and v not in _YALE for v in first)
    lookup = _NATIVE if native else _YALE
    columns = [lookup.get(v) for v in first]
    display = [lookup.get(v) for v in second]
    # A full native template identifies its display row explicitly. Some older
    # native files have only the banner in row one and every field in row two.
    second_is_header = native_marker and (second[:1] == ["field name"] or (not any(columns) and any(display)))
    if any(columns):
        matches = [(raw_label.strip() == raw_code.strip(), lookup.get(_key(raw_label)) == col)
                   for col, raw_label, raw_code in zip(columns, rows[1] if second else [], rows[0])
                   if col and raw_label.strip()]
        has_alias = bool(matches) and all(aligned for _, aligned in matches) and any(not same for same, _ in matches)
        # With renamed headings, a nonnumeric value under a depth code is a
        # heading if the next component actually has its numeric depth there.
        if "depth" in first and len(rows) > 2:
            i = first.index("depth")
            if len(second) > i and len(rows[2]) > i and second[i] and not second[i].isdecimal() and rows[2][i].strip().isdecimal():
                second_is_header = True
        second_is_header = second_is_header or has_alias
    count = header_rows or (2 if second_is_header else 1)
    if count == 2:
        if native_marker and not any(columns):
            columns = display
        else:
            for index, label in enumerate(display[:len(first)]):
                if not first[index]:
                    columns[index] = label
    if not any(columns):
        return None
    return Header("native-csv" if native else "yale-csv", tuple(columns), count)
