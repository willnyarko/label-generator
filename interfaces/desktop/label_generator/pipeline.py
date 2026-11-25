"""Analyze collection data for preview and generate the selected labels and row files."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Optional

from .engine.content import say as engine_text
from .engine.lrr.derive import derive_lrr
from .engine.lrr.selection import Scope, Selection, read_boxes, read_numbers
from .engine.models.lrr import LrrBundle
from .engine.models.ycar import YcarRecord
from .engine.notices import InputError, label_notes, notice
from .engine.projections.rows import write_rows
from .engine.readers import read_input
from .engine.readers.detect import detect_input_kind
from .projections.excel import write_excel
from .projections.html import write_html_outputs
from .projections.options import DEFAULT_RENDER_OPTIONS, RenderOptions, without_folder_details
from .projections.word import write_word_outputs
from .validation import Finding, ValidationError

FolderGeneration = Literal["derive", "none"]
NumberingPreference = Literal["continuous", "non-continuous"]


Labels = Literal["both", "folders", "boxes"]


def _derive(record: YcarRecord, numbering: Optional[NumberingPreference], first_folder: int) -> LrrBundle:
    scheme = "through-collection" if numbering == "continuous" else "per-box"
    return derive_lrr(record, numbering_preference=scheme, first_folder=first_folder)


def _selection(bundle: LrrBundle, scope: Scope, choices: str) -> Selection:
    if scope == "all":
        return Selection()
    if scope == "boxes":
        boxes = read_boxes(choices, list(dict.fromkeys(box.box for box in bundle.boxes)))
        if boxes:
            return Selection(scope, boxes=boxes, typed=choices)
        raise ValidationError(Finding("", engine_text("selection.boxes_invalid"), ""))

    if not any(bundle.aggregates):
        raise ValidationError(notice("nothing-to-label", variant="selection"))
    groups = read_numbers(choices, len(bundle.aggregates))
    if groups:
        return Selection(scope, aggregates=groups, typed=choices)
    raise ValidationError(Finding("", engine_text("selection.aggregates_invalid", count=len(bundle.aggregates)), ""))


def _label_rows(chosen: LrrBundle, labels: Labels, omit_box_folders: bool) -> LrrBundle:
    folders = [] if labels == "boxes" else chosen.folders
    boxes = [] if labels == "folders" else chosen.boxes
    if not folders and not boxes:
        raise ValidationError(notice("nothing-to-label", variant="selection"))
    if labels == "boxes" and all(box.placeholder_box for box in boxes):
        raise ValidationError(notice("nothing-to-label", variant="no_box"))
    if omit_box_folders:
        boxes = without_folder_details(boxes)
    return replace(chosen, folders=folders, boxes=boxes)


DEFAULT_FORMATS = ("word", "csv")
FORMATS = (*DEFAULT_FORMATS, "html", "excel")


@dataclass
class AnalysisResult:
    """What a read and derivation produced, held so a preview and a later generate use the same data."""
    record: YcarRecord
    bundle: LrrBundle
    input_kind: str
    numbering_required: bool
    effective_numbering: NumberingPreference
    folder_generation: FolderGeneration
    stem: str
    first_folder: int = 1

    def summary(self) -> dict:
        """The facts a surface shows before anything is written, as plain data."""
        return {
            "input_kind": self.input_kind,
            "collection": self.record.primary_title(),
            "call_number": self.record.call_number(),
            "collection_provenance": self.record.title_provenance,
            "call_number_provenance": self.record.call_number_provenance,
            "identity_missing": self.record.identity_missing(),
            "repository": self.record.repository_display(),
            "repository_code": self.record.repository.code if self.record.repository else "",
            "repository_provenance": self.record.repository_provenance,
            "folder_count": len(self.bundle.folders),
            "box_count": len(self.bundle.boxes),
            "box_choices": list(dict.fromkeys(box.box for box in self.bundle.boxes)),
            "aggregate_choices": self.bundle.aggregates if any(self.bundle.aggregates) else [],
            "stated_folders": self.bundle.stated_folders,
            "folders_already_numbered": self.bundle.stated_scheme is not None,
            "numbering_required": self.numbering_required,
            "default_numbering": self.effective_numbering,
            "folder_generation": self.folder_generation,
        }


@dataclass
class PipelineResult:
    """What a generate wrote: the rows, the files, and any warnings to show."""
    bundle: LrrBundle
    output_paths: list[Path]
    stem: str
    warnings: list[Finding] = field(default_factory=list)


def analyze(
    input_path: Path,
    *,
    numbering_preference: Optional[NumberingPreference] = None,
    folder_generation: FolderGeneration = "derive",
    first_folder: int = 1,
    header_rows: Optional[int] = None,
    collection: Optional[str] = None,
    call_number: Optional[str] = None,
    repository: Optional[str] = None,
) -> AnalysisResult:
    """Detect, read, and derive a bundle for preview (no files written).

    Nonblank collection, call number and repository overrides are applied to
    the source before deriving any label rows.
    """
    try:
        kind = detect_input_kind(input_path)
        record = read_input(
            input_path, input_kind=kind, header_rows=header_rows,
            collection=collection, call_number=call_number, repository=repository,
        )
    except InputError as exc:
        raise ValidationError(exc.notice) from exc
    except OSError as exc:
        error = notice("cannot-open", path=input_path.name, reason=exc.strerror or str(exc))
        raise ValidationError(error) from exc
    bundle = _derive(record, numbering_preference, first_folder)
    if not bundle.folders and not bundle.boxes:
        variant = None if kind == "ead" else "csv"
        raise ValidationError(notice("nothing-to-label", variant=variant, name=input_path.name))
    if folder_generation == "none":
        bundle = _label_rows(bundle, "boxes", omit_box_folders=True)
    return AnalysisResult(
        first_folder=first_folder,
        record=record,
        bundle=bundle,
        input_kind=kind,
        numbering_required=folder_generation == "derive" and bundle.stated_scheme is None,
        effective_numbering="continuous" if bundle.numbering == "through-collection" else "non-continuous",
        folder_generation=folder_generation,
        stem=_output_stem(record.primary_title(), record.call_number()),
    )


def select_labels(
    analysis: AnalysisResult,
    *,
    labels: Optional[Labels] = None,
    scope: Scope = "all",
    choices: str = "",
    folder_generation: Optional[FolderGeneration] = None,
    numbering_preference: Optional[NumberingPreference] = None,
    omit_box_folders: bool = False,
) -> tuple[LrrBundle, str]:
    """Select from the fully numbered collection for either preview or download."""
    whole = analysis.bundle
    if not whole.folders and not whole.boxes:
        raise ValidationError("no_rows")
    numbering = numbering_preference or analysis.effective_numbering
    if numbering != analysis.effective_numbering or analysis.folder_generation == "none":
        whole = _derive(analysis.record, numbering, analysis.first_folder)
    # Earlier desktop clients used "none" for boxes only with no folder details.
    legacy_box_only = labels is None and (folder_generation or analysis.folder_generation) == "none"
    selected_type = labels or ("boxes" if legacy_box_only else "both")
    selection = _selection(whole, scope, choices)
    rows = _label_rows(selection.apply(whole), selected_type, omit_box_folders or legacy_box_only)
    return rows, analysis.stem + selection.suffix


def generate(
    analysis: AnalysisResult,
    output_dir: Path,
    *,
    numbering_preference: Optional[NumberingPreference] = None,
    folder_generation: Optional[FolderGeneration] = None,
    labels: Optional[Labels] = None,
    scope: Scope = "all",
    choices: str = "",
    formats: Optional[list[str]] = None,
    render_options: Optional[RenderOptions] = None,
) -> PipelineResult:
    """Write the label files for an analysis and return their paths with any warnings.

    Unspecified settings take the analysis value or the desktop default.
    """
    opts = render_options or DEFAULT_RENDER_OPTIONS
    bundle, stem = select_labels(
        analysis, labels=labels, scope=scope, choices=choices, numbering_preference=numbering_preference,
        folder_generation=folder_generation, omit_box_folders=opts.box_folder_text == "omit",
    )
    if len(stem) <= 180:
        output_paths = _write_formats(bundle, output_dir, stem, formats, opts)
    else:
        # Keep the full selection in the filename whenever it fits. The selected stock,
        # folder layout and formats determine which filename suffixes are needed.
        output_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=output_dir) as staging:
            files = _write_formats(bundle, Path(staging), "", formats, opts)
            if any(len(stem + path.name) > 255 for path in files) or len(zip_download_name(stem)) > 255:
                digest = sha256(choices.encode("utf-8")).hexdigest()[:12]
                stem = f"{analysis.stem}_{scope}_{digest}"
            output_paths = [path.replace(output_dir / (stem + path.name)) for path in files]

    warnings = [Finding(str(note.number), note.text, note.fix, heading=note.heading)
                for note in label_notes(analysis.record, bundle)]
    return PipelineResult(bundle=bundle, output_paths=output_paths, stem=stem, warnings=warnings)


def _write_formats(
    bundle: LrrBundle, output_dir: Path, stem: str, formats: Optional[list[str]], opts: RenderOptions,
) -> list[Path]:
    output_paths: list[Path] = []
    selected = formats or DEFAULT_FORMATS
    if "all" in selected:
        selected = FORMATS
    if "word" in selected:
        output_paths.extend(write_word_outputs(bundle, output_dir, stem, options=opts))
    if "csv" in selected:
        output_paths.extend(write_rows(bundle, output_dir, stem))
    if "html" in selected:
        output_paths.extend(write_html_outputs(bundle, output_dir, stem, options=opts))
    if "excel" in selected:
        output_paths.extend(write_excel(bundle, output_dir, stem, options=opts))
    return output_paths


def _output_stem(collection: str, call_number: str) -> str:
    """A file name stem built from the collection name and call number, limited to safe characters."""
    def _safe(part: str, limit: int) -> str:
        # "Bégon" becomes "Begon", not "B_gon": accents are split off before the rest is filtered.
        plain = unicodedata.normalize("NFKD", part)
        cleaned = "".join(
            c if c.isascii() and (c.isalnum() or c in "._-") else "_"
            for c in plain
            if not unicodedata.combining(c)
        )
        return cleaned[:limit].strip("_") or "collection"

    safe_coll = _safe(collection, 40)
    safe_call = _safe(call_number, 20)
    return f"{safe_coll}_{safe_call}"


def zip_download_name(stem: str) -> str:
    """The name offered for the zip of all outputs."""
    return f"{stem}_labels.zip"
