"""Excel QA projection."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from ..engine.models.lrr import LrrBundle
from .options import DEFAULT_RENDER_OPTIONS, RenderOptions


def write_excel(
    bundle: LrrBundle,
    output_dir: Path,
    stem: str,
    *,
    options: RenderOptions | None = None,
) -> list[Path]:
    """Write the folder and box rows as Excel workbooks in ``output_dir`` and return their paths."""
    opts = options or DEFAULT_RENDER_OPTIONS
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    if bundle.folders:
        folder_path = output_dir / f"{stem}_folder.xlsx"
        _write_sheet(folder_path, bundle.folders_as_dicts())
        paths.append(folder_path)

    if bundle.boxes:
        box_path = output_dir / f"{stem}_box.xlsx"
        box_rows = bundle.boxes_as_dicts()
        if opts.box_folder_text == "omit":
            for row in box_rows:
                row["FOLDER_COUNT"] = None
                row["FIRST_FOLDER"] = None
                row["LAST_FOLDER"] = None
        _write_sheet(box_path, box_rows)
        paths.append(box_path)
    return paths


def _write_sheet(path: Path, rows: list[dict]) -> None:
    """Save ``rows`` as a one-sheet workbook whose first row is the column headings."""
    wb = Workbook()
    ws = wb.active
    if not rows:
        wb.save(path)
        return
    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    wb.save(path)
