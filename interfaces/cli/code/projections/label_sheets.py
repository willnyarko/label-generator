"""The Avery sheet measures, read from ``config/label_sheets.toml``.

``SHEET_SPECS["avery-5161"]`` is that sheet's table with the page size added,
so a writer needs one lookup for everything it lays out. ``FOLDER_SHEET`` names
the sheet folder labels use; boxes choose theirs in ``lrr/box_kinds.py``.
"""

from __future__ import annotations

import tomllib

from content import CONFIG

_FILE = CONFIG / "label_sheets.toml"


def _load() -> tuple[dict[str, dict], str]:
    table = tomllib.loads(_FILE.read_text(encoding="utf-8"))
    page = {f"page_{name}": value for name, value in table.pop("page").items()}
    folder_sheet = table.pop("folder_stock")["sheet"]
    return {sheet: {**measures, **page} for sheet, measures in table.items()}, folder_sheet


SHEET_SPECS, FOLDER_SHEET = _load()
