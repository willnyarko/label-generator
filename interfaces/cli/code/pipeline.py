"""The pipeline: a single run from start to finish, irrespective of how the program starts. It contains two main functions:

(1) ``analyze()``: reads the input file and works out the collection's resource-level identity (its name, call number and repository) and every label it could have.
(2) ``generate()``: takes the choices the person has made, keeps the labels they asked for, writes the output files (currently Word and CSV), and adds any notes they should check at the end of the run.

The rules in this file apply to naming and writing the output files: ``analyze()`` prepares what they need, and ``generate()`` applies them. This file also checks whether user must be asked about folder numbering at all.

For more details about the rules, see ``../docs/technical/rules.md``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Optional

from lrr.derive import derive_lrr
from lrr.selection import Selection
from models.lrr import MISSING_BOX_SENTINEL, BoxLRR, LrrBundle, NumberingScheme
from models.ycar import YcarRecord
from notices import InputError, Notice, notice
from projections.options import DEFAULT_RENDER_OPTIONS, RenderOptions
from projections.rows import write_rows
from projections.word import write_word_outputs
from readers import read_input
from readers.detect import detect_input_kind

Labels = Literal["both", "folders", "boxes"]


@dataclass
class AnalysisResult:
    record: YcarRecord
    bundle: LrrBundle
    input_kind: str
    stem: str

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
) -> AnalysisResult:
    kind = detect_input_kind(input_path)
    record = read_input(input_path, collection=collection, call_number=call_number, repository=repository)
    return AnalysisResult(
        record=record,
        bundle=derive_lrr(record),
        input_kind=kind,
        stem=_output_stem(record.primary_title(), record.call_number()),
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
        raise InputError("nothing-to-label")
    if labels == "boxes" and all(box.box == MISSING_BOX_SENTINEL for box in bundle.boxes):
        raise InputError("nothing-to-label")

    stem = analysis.stem + selection.suffix
    output_paths = write_word_outputs(bundle, output_dir, stem, options=opts)
    output_paths += write_rows(bundle, output_dir, stem)

    notes: list[Notice] = []
    if any(row.box == MISSING_BOX_SENTINEL for row in [*bundle.folders, *bundle.boxes]):
        notes.append(notice("missing-box", sentinel=MISSING_BOX_SENTINEL))
    if analysis.record.identity_missing():
        notes.append(notice("missing-identity"))
    if analysis.record.repository is None:
        notes.append(notice("no-repository"))
    if analysis.record.replaced_characters:
        replaced = analysis.record.replaced_characters
        notes.append(
            notice(
                "replaced-characters",
                count=len(replaced),
                characters=", ".join(dict.fromkeys(f"U+{ord(ch):04X}" for _, ch in replaced)),
                lines=", ".join(str(line) for line in dict.fromkeys(line for line, _ in replaced)),
            )
        )

    return PipelineResult(bundle=bundle, output_paths=output_paths, notes=notes)


def _without_folders(box: BoxLRR) -> BoxLRR:
    return replace(box, folder_count=None, first_folder=None, last_folder=None)


def _output_stem(collection: str, call_number: str) -> str:
    def _safe(part: str, limit: int) -> str:
        plain = unicodedata.normalize("NFKD", part)
        cleaned = "".join(
            c if c.isascii() and (c.isalnum() or c in "._-") else "_"
            for c in plain
            if not unicodedata.combining(c)
        )
        return cleaned[:limit].strip("_") or "collection"

    return f"{_safe(collection, 40)}_{_safe(call_number, 20)}"
