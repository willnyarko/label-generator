"""Write Word sheets using the selected desktop layout and box stock."""

from dataclasses import replace
from pathlib import Path

from docx import Document

from ..engine.lrr.box_kinds import STOCKS
from ..engine.models.lrr import BoxLRR, LrrBundle
from ..engine.projections import word
from ..engine.projections.label_sheets import SHEET_SPECS
from ..engine.projections.options import RenderOptions as WordOptions
from ..engine.projections.typography import typography
from .options import DEFAULT_RENDER_OPTIONS, BoxFolderText, RenderOptions, stock_kind, without_folder_details

render_folder_docx = word.render_folder_docx


def write_word_outputs(
    bundle: LrrBundle, output_dir: Path, stem: str, *, options: RenderOptions | None = None,
) -> list[Path]:
    opts = options or DEFAULT_RENDER_OPTIONS
    show_folders = opts.box_folder_text == "show"
    if not show_folders:
        bundle = replace(bundle, boxes=without_folder_details(bundle.boxes))
    word_options = WordOptions(
        folder_layout=opts.folder_layout,
        box_kind=stock_kind(opts.box_format) if bundle.boxes else "auto",
        box_folders=show_folders,
    )
    return word.write_word_outputs(bundle, output_dir, stem, options=word_options)


def render_box_docx(
    boxes: list[BoxLRR], *, sheet: str = STOCKS["full"].sheet, vertical: bool = False,
    box_folder_text: BoxFolderText = "show",
) -> Document:
    """Render a single sheet using the existing desktop sheet and orientation arguments."""
    rows = boxes if box_folder_text == "show" else without_folder_details(boxes)
    for kind, stock in STOCKS.items():
        if (sheet, vertical) == (stock.sheet, stock.vertical):
            return word.render_box_docx(rows, kind=kind)

    # Direct callers can also request a custom pairing of sheet and orientation.
    spec = SHEET_SPECS[sheet]
    doc = Document()
    word._setup_page(doc, spec)
    word._paginate_boxes(doc, spec, rows, vertical=vertical, type_=typography()["box"]["full"])
    return doc
