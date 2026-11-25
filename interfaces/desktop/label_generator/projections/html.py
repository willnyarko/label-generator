"""HTML label sheet projection (Avery geometry)."""

from __future__ import annotations

from pathlib import Path

from ..lrr.box_format import STOCKS, group_boxes_by_format
from ..engine.models.lrr import BoxLRR, FolderLRR, LrrBundle
from ..content import say
from .label_content import ancestor_chain, box_folder_line, box_heading, box_range_text
from .options import BoxFolderText, BoxFormat, DEFAULT_RENDER_OPTIONS, RenderOptions, stock_kind
from .sheet_specs import FOLDER_SHEET, SHEET_SPECS
from .typography import proof_settings, typography


def render_folder_html(
    bundle: LrrBundle,
    *,
    options: RenderOptions | None = None,
) -> str:
    """The folder labels as one printable HTML document."""
    opts = options or DEFAULT_RENDER_OPTIONS
    spec = SHEET_SPECS[FOLDER_SHEET]
    if opts.folder_layout == "left":
        body = _render_folder_left(bundle.folders, spec)
    else:
        body = _render_folder_regular(bundle.folders, spec)
    return _html_document(spec, say("labels.folder_sheet_title"), body, vertical=False)


def render_box_html(
    bundle: LrrBundle,
    *,
    options: RenderOptions | None = None,
) -> str:
    """The box labels as one printable HTML document, grouped by stock."""
    opts = options or DEFAULT_RENDER_OPTIONS
    groups = group_boxes_by_format(bundle.boxes, choice=opts.box_format)
    if not groups:
        spec = SHEET_SPECS[STOCKS["default"].sheet]
        return _html_document(spec, say("labels.box_sheet_title"), "", vertical=False)
    pages: list[str] = []
    title = say("labels.box_sheet_title")
    vertical = False
    for kind, boxes in groups.items():
        stock = STOCKS[kind]
        spec = SHEET_SPECS[stock.sheet]
        group_vertical = stock.vertical
        vertical = vertical or group_vertical
        pages.append(
            _render_box_pages(
                boxes,
                spec,
                kind=kind,
                box_folder_text=opts.box_folder_text,
            )
        )
    return _html_document(
        SHEET_SPECS[STOCKS[next(iter(groups))].sheet],  # the sheets share one page size
        title,
        "".join(pages),
        vertical=vertical,
    )


def write_html_outputs(
    bundle: LrrBundle,
    output_dir: Path,
    stem: str,
    *,
    options: RenderOptions | None = None,
) -> list[Path]:
    """Write the folder and box proofs as HTML files in ``output_dir`` and return their paths."""
    opts = options or DEFAULT_RENDER_OPTIONS
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    if bundle.folders:
        folder_suffix = "_left_labels" if opts.folder_layout == "left" else "_folder_labels"
        folder_path = output_dir / f"{stem}{folder_suffix}.html"
        folder_path.write_text(render_folder_html(bundle, options=opts), encoding="utf-8")
        paths.append(folder_path)

    groups = group_boxes_by_format(bundle.boxes, choice=opts.box_format)
    for kind, boxes in groups.items():
        stock = STOCKS[kind]
        spec = SHEET_SPECS[stock.sheet]
        vertical = stock.vertical
        box_path = output_dir / f"{stem}{stock.suffix}.html"
        body = _render_box_pages(
            boxes,
            spec,
            kind=kind,
            box_folder_text=opts.box_folder_text,
        )
        box_path.write_text(_html_document(spec, say("labels.box_sheet_title"), body, vertical=vertical), encoding="utf-8")
        paths.append(box_path)

    return paths


def _render_folder_regular(folders: list[FolderLRR], spec: dict) -> str:
    """Folder labels as pages of two-label rows, one folder to a row."""
    per_page = spec["rows"]
    pages: list[str] = []
    for page_start in range(0, max(len(folders), 1), per_page):
        chunk = folders[page_start : page_start + per_page]
        rows_html: list[str] = []
        for row in chunk:
            rows_html.append(_folder_regular_row_html(row, spec))
        empty = per_page - len(chunk)
        rows_html.extend(_empty_regular_row(spec) for _ in range(empty))
        pages.append(f'<div class="sheet folder-regular">{"".join(rows_html)}</div>')
    return "".join(pages) if pages else _empty_regular_sheet(spec)


def _render_folder_left(folders: list[FolderLRR], spec: dict) -> str:
    """Folder labels as pages that carry only each folder's left-hand label, two across, filled row by row."""
    cols, rows = spec["cols"], spec["rows"]
    per_page = cols * rows
    pages: list[str] = []
    for page_start in range(0, max(len(folders), 1), per_page):
        chunk = folders[page_start : page_start + per_page]
        row_html: list[str] = []
        for r in range(rows):
            cells: list[str] = []
            for c in range(cols):
                idx = r * cols + c
                if idx < len(chunk):
                    cells.append(_folder_left_cell_html(chunk[idx]))
                else:
                    cells.append(_empty_left_cell())
            row_html.append(_folder_left_row_html(cells[0], cells[1], spec))
        pages.append(f'<div class="sheet folder-left">{"".join(row_html)}</div>')
    return "".join(pages)


def _render_box_pages(
    boxes: list[BoxLRR],
    spec: dict,
    *,
    kind: BoxFormat,
    box_folder_text: BoxFolderText,
) -> str:
    """Box labels as pages two across, filled row by row."""
    vertical = STOCKS[kind].vertical
    box_type = typography()["box"][stock_kind(kind)]
    cols, rows = spec["cols"], spec["rows"]
    per_page = cols * rows
    pages: list[str] = []
    for page_start in range(0, max(len(boxes), 1), per_page):
        chunk = boxes[page_start : page_start + per_page]
        row_html: list[str] = []
        for r in range(rows):
            left = chunk[r * cols] if r * cols < len(chunk) else None
            right = chunk[r * cols + 1] if r * cols + 1 < len(chunk) else None
            row_html.append(
                _box_row_html(
                    left,
                    right,
                    spec,
                    vertical=vertical,
                    box_folder_text=box_folder_text,
                )
            )
        cls = "sheet box-sheet vertical" if vertical else "sheet box-sheet"
        pages.append(
            f'<div class="{cls}" style="width:{spec["page_width_in"]}in;'
            f'font-family:{_esc(box_type["font"])}, sans-serif;font-size:{box_type["size"]}pt;'
            f'padding:{spec["margin_top_in"]}in {spec["margin_side_in"]}in 0;">'
            f'{"".join(row_html)}</div>'
        )
    return "".join(pages)


def _folder_left_row_html(left: str, right: str, spec: dict) -> str:
    h, g = spec["label_height_in"], spec["gutter_in"]
    return (
        f'<div class="folder-left-row" style="height:{h}in">'
        f"{left}<div class=\"gutter\" style=\"width:{g}in\"></div>{right}</div>"
    )


def _empty_left_cell() -> str:
    return '<div class="label left-only empty"></div>'


def _box_row_html(
    left: BoxLRR | None,
    right: BoxLRR | None,
    spec: dict,
    *,
    vertical: bool,
    box_folder_text: BoxFolderText,
) -> str:
    """One row of box labels, either side of which may be empty."""
    h, g = spec["label_height_in"], spec["gutter_in"]
    w = spec["label_width_in"]
    cell_style = f"width:{w}in;height:{h}in;flex:0 0 {w}in"
    left_cell = (
        _box_label_html(
            left,
            vertical=vertical,
            style=cell_style,
            box_folder_text=box_folder_text,
        )
        if left
        else f'<div class="label box-label empty" style="{cell_style}"></div>'
    )
    right_cell = (
        _box_label_html(
            right,
            vertical=vertical,
            style=cell_style,
            box_folder_text=box_folder_text,
        )
        if right
        else f'<div class="label box-label empty" style="{cell_style}"></div>'
    )
    return (
        f'<div class="box-row" style="height:{h}in">'
        f"{left_cell}<div class=\"gutter\" style=\"width:{g}in\"></div>{right_cell}</div>"
    )


def _folder_regular_row_html(row: FolderLRR, spec: dict) -> str:
    """One row of the regular folder layout: the left label and its matching right label."""
    w = spec["label_width_in"]
    h = spec["label_height_in"]
    g = spec["gutter_in"]
    left = f"""<div class="label-left" style="width:{w}in;height:{h}in">
      <div class="call">{_esc(row.call_number)}</div>
      <div>{_esc(box_folder_line(row))}</div>
      <div class="collection">{_esc(row.collection)}</div>
      <div class="series">{_esc(row.series)}</div>
    </div>"""
    right = f"""<div class="label-right" style="width:{w}in;height:{h}in">
      <div class="ancestors">{_esc(ancestor_chain(row))}</div>
      <div class="title">{_esc(row.folder_title)}</div>
      <div class="dates">{_esc(row.folder_dates)}</div>
    </div>"""
    return (
        f'<div class="folder-row" style="height:{h}in">'
        f"{left}<div class=\"gutter\" style=\"width:{g}in\"></div>{right}</div>"
    )


def _folder_left_cell_html(row: FolderLRR) -> str:
    return f"""<div class="label left-only">
      <div class="call">{_esc(row.call_number)}</div>
      <div>{_esc(box_folder_line(row))}</div>
      <div class="collection">{_esc(row.collection)}</div>
      <div class="series">{_esc(row.series)}</div>
    </div>"""


def _box_label_html(
    row: BoxLRR,
    *,
    vertical: bool,
    style: str,
    box_folder_text: BoxFolderText,
) -> str:
    vclass = " vertical-text" if vertical else ""
    return f"""<div class="label box-label{vclass}" style="{style}">
      <div class="repository">{_esc(row.repository)}</div>
      <div class="collection">{_esc(row.collection)}</div>
      <div class="call">{_esc(row.call_number)}</div>
      <div class="series">{_esc(row.series)}</div>
      <div class="box">{_esc(box_heading(row))}</div>
      <div class="range">{_esc(box_range_text(row, display=box_folder_text))}</div>
    </div>"""


def _empty_regular_row(spec: dict) -> str:
    w, h, g = spec["label_width_in"], spec["label_height_in"], spec["gutter_in"]
    return (
        f'<div class="folder-row" style="height:{h}in">'
        f'<div class="label empty" style="width:{w}in;height:{h}in"></div>'
        f'<div class="gutter" style="width:{g}in"></div>'
        f'<div class="label empty" style="width:{w}in;height:{h}in"></div></div>'
    )


def _empty_regular_sheet(spec: dict) -> str:
    return f'<div class="sheet folder-regular">{_empty_regular_row(spec)}</div>'


def _html_document(spec: dict, title: str, body: str, *, vertical: bool) -> str:
    """Wrap page markup in a complete document with the sheet's page size, margins and the configured type."""
    w = spec["label_width_in"]
    h = spec["label_height_in"]
    mt = spec["margin_top_in"]
    ms = spec["margin_side_in"]
    pw = spec["page_width_in"]
    ph = spec["page_height_in"]
    vert_css = ""
    if vertical:
        vert_css = """
  .box-label.vertical-text {
    writing-mode: vertical-rl;
    transform: rotate(180deg);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }"""
    folder = typography()["folder"]
    proof = proof_settings()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{_esc(title)}</title>
<style>
  @page {{ size: {pw}in {ph}in; margin: 0; }}
  body {{ font-family: {_esc(folder["font"])}, sans-serif; font-size: {folder["size"]}pt; margin: 0; }}
  .sheet {{
    box-sizing: border-box;
    width: {pw}in;
    padding: {mt}in {ms}in 0 {ms}in;
    page-break-after: always;
  }}
  .folder-regular .folder-row,
  .folder-left-row,
  .box-row {{
    display: flex;
    flex-direction: row;
    align-items: stretch;
  }}
  .folder-left-row .label,
  .box-row .label {{
    flex: 0 0 {w}in;
    width: {w}in;
    height: {h}in;
  }}
  .box-sheet {{
    display: flex;
    flex-direction: column;
  }}
  .label {{
    box-sizing: border-box;
    padding: {proof["label_padding_in"]}in;
    overflow: hidden;
    border: {proof["cut_guide"]};
  }}
  .label.empty {{ border: none; }}
  .label-left, .label-right {{ box-sizing: border-box; padding: {proof["label_padding_in"]}in; overflow: hidden; }}
  .label-left {{ border: {proof["cut_guide"]}; border-right: none; }}
  .label-right {{ border: {proof["cut_guide"]}; border-left: none; }}
  .box-label {{
    text-align: center;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }}
  .gutter {{ flex-shrink: 0; }}{vert_css}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
