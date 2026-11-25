"""The pipeline runs from start to finish, irrespective of how the program starts.

analyze() reads the input file and works out the collection's resource-level
identity (its name, call number and repository) and the labels it could have.

generate() handles the choices the user has made:
    - keeps the labels they asked for
    - writes the Word sheets and CSV rows
    - adds any notes they should check at the end of the run

For the rules on naming and writing output files, see ../docs/technical/rules.md.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Optional

from lrr.derive import derive_lrr
from lrr.selection import Selection
from models.lrr import BoxLRR, LrrBundle, NumberingScheme
from models.ycar import YcarRecord
from notices import InputError, Notice, label_notes
from projections.options import DEFAULT_RENDER_OPTIONS, RenderOptions
from projections.outputs import write_outputs
from readers import read_input
from readers.detect import detect_input_kind

Labels = Literal["both", "folders", "boxes"]


@dataclass
class AnalysisResult:
    record: YcarRecord
    bundle: LrrBundle
    input_kind: str
    stem: str
    filename: str = ""

    def require_components(self) -> None:
        if not self.bundle.folders and not self.bundle.boxes:
            variant = None if self.input_kind == "ead" else "csv"
            raise InputError("nothing-to-label", variant=variant, name=self.filename or self.stem)

    @property
    def numbering_required(self) -> bool:
        return self.bundle.stated_scheme is None


@dataclass
class PipelineResult:
    bundle: LrrBundle
    output_paths: list[Path]
    notes: list[Notice] = field(default_factory=list)


def analyze(
    input_path: Path,
    *,
    collection: Optional[str] = None,
    call_number: Optional[str] = None,
    repository: Optional[str] = None,
    header_rows: Optional[int] = None,
) -> AnalysisResult:
    try:
        kind = detect_input_kind(input_path)
        record = read_input(input_path, collection=collection, call_number=call_number, repository=repository,
                            header_rows=header_rows, input_kind=kind)
    except OSError as exc:
        raise InputError("cannot-open", path=input_path.name, reason=exc.strerror or str(exc)) from exc
    return AnalysisResult(
        record=record,
        bundle=derive_lrr(record),
        input_kind=kind,
        stem=_output_stem(record.primary_title(), record.call_number()),
        filename=input_path.name,
    )


def generate(
    analysis: AnalysisResult,
    output_dir: Path,
    *,
    labels: Labels = "both",
    selection: Selection = Selection(),
    numbering_preference: Optional[NumberingScheme] = None,
    first_folder: int = 1,
    render_options: Optional[RenderOptions] = None,
) -> PipelineResult:
    analysis.require_components()
    whole = derive_lrr(analysis.record, numbering_preference=numbering_preference, first_folder=first_folder)
    chosen = selection.apply(whole)
    opts = render_options or DEFAULT_RENDER_OPTIONS
    boxes = chosen.boxes if opts.box_folders else [_without_folders(box) for box in chosen.boxes]
    bundle = replace(
        chosen,
        folders=chosen.folders if labels != "boxes" else [],
        boxes=boxes if labels != "folders" else [],
    )
    if not bundle.folders and not bundle.boxes:
        raise InputError("nothing-to-label", variant="selection", change_settings=True)
    if labels == "boxes" and all(box.placeholder_box for box in bundle.boxes):
        raise InputError("nothing-to-label", variant="no_box", change_settings=True)

    stem = analysis.stem + selection.suffix
    output_paths = write_outputs(bundle, output_dir, stem, opts)

    return PipelineResult(bundle=bundle, output_paths=output_paths, notes=label_notes(analysis.record, bundle))


def _without_folders(box: BoxLRR) -> BoxLRR:
    return replace(box, folder_count=None, first_folder=None, last_folder=None)


def _output_stem(collection: str, call_number: str) -> str:
    def _safe(part: str, limit: int) -> str:
        # "Bégon" becomes "Begon", not "B_gon": accents are split off before the rest is filtered.
        plain = unicodedata.normalize("NFKD", part)
        cleaned = "".join(
            c if c.isascii() and (c.isalnum() or c in "._-") else "_"
            for c in plain
            if not unicodedata.combining(c)
        )
        return cleaned[:limit].strip("_") or "collection"

    return f"{_safe(collection, 40)}_{_safe(call_number, 20)}"
