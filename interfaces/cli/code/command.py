"""Non-interactive arguments for the same pipeline used by the guided CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from content import say
from lrr.selection import Selection, read_boxes, read_numbers
from notices import InputError
from pipeline import AnalysisResult, PipelineResult, analyze, generate
from projections.options import RenderOptions
from repositories import repositories


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="label-generator run", allow_abbrev=False,
                                     description="Generate Word labels and CSV rows without terminal prompts.")
    parser.add_argument("file", type=Path, help="ArchivesSpace EAD XML or bulk import CSV")
    parser.add_argument("--output-dir", type=Path, help="destination (default: beside the input)")
    parser.add_argument("--collection", help="collection name to print")
    parser.add_argument("--call-number", help="collection call number to print")
    parser.add_argument("--repository", choices=[r.code for r in repositories()], help="repository code")
    parser.add_argument("--labels", choices=["both", "folders", "boxes"], default="both")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--boxes", help='box indicators and ranges in shelf order, e.g. "2, 7-9"')
    scope.add_argument("--aggregates", help='top-level menu numbers, e.g. "1, 3-5"')
    parser.add_argument("--list-choices", action="store_true", help="list boxes and numbered aggregates, then exit")
    parser.add_argument("--numbering", choices=["per-box", "through-collection"],
                        help="scheme for folders when the source does not establish one (default: per-box)")
    parser.add_argument("--first-folder", type=int, help="start a through-collection count at this number")
    parser.add_argument("--folder-layout", choices=["regular", "left"], help="left and right (default), or left only")
    parser.add_argument("--box-kind", choices=["auto", "full", "half-hollinger", "flat"],
                        help="box stock (default: match each box type)")
    parser.add_argument("--box-folders", choices=["show", "omit"], help="include folder details on boxes (default: show)")
    parser.add_argument("--csv-header-rows", type=int, choices=[1, 2], help="set the header row count for an ambiguous CSV")
    return parser


def _selection(args, analysis: AnalysisResult, parser: argparse.ArgumentParser) -> Selection:
    if args.boxes is not None:
        numbers = read_boxes(args.boxes, [b.box for b in analysis.bundle.boxes])
        if not numbers:
            parser.error("--boxes must name boxes in this file (see --list-choices)")
        return Selection("boxes", boxes=numbers, typed=args.boxes)
    if args.aggregates is not None:
        groups = analysis.bundle.aggregates
        numbers = read_numbers(args.aggregates, len(groups))
        if not any(groups) or not numbers:
            parser.error("--aggregates must name top-level choices in this file (see --list-choices)")
        return Selection("aggregates", aggregates=numbers, typed=args.aggregates)
    return Selection()


def _validate(args, analysis: AnalysisResult, parser: argparse.ArgumentParser) -> None:
    if args.labels == "folders" and (args.box_kind or args.box_folders):
        parser.error("--box-kind and --box-folders apply when making box labels")
    if args.labels == "boxes" and args.folder_layout:
        parser.error("--folder-layout applies when making folder labels")
    if args.labels == "boxes" and args.box_folders == "omit" and (args.numbering or args.first_folder is not None):
        parser.error("folder numbering applies when the labels show folders")
    scheme = analysis.bundle.stated_scheme
    if args.numbering and scheme and args.numbering != scheme:
        parser.error(f"the source establishes {scheme} numbering")
    if args.first_folder is not None and (args.first_folder < 1 or args.numbering != "through-collection" or analysis.bundle.stated_folders):
        parser.error("--first-folder requires a positive number, --numbering through-collection and no source folder numbers")


def run_command(argv: list[str], report: Callable[[AnalysisResult, PipelineResult, Path, str], None]) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv[1:] if argv[:1] == ["run"] else argv)
        if args.csv_header_rows and args.file.suffix.lower() != ".csv":
            parser.error("--csv-header-rows applies to CSV files")
        analysis = analyze(args.file, collection=args.collection, call_number=args.call_number,
                           repository=args.repository, header_rows=args.csv_header_rows)
        analysis.require_components()
        if args.list_choices:
            print(say("cli.ask.boxes_list"))
            print(", ".join(dict.fromkeys(box.box for box in analysis.bundle.boxes)))
            if any(analysis.bundle.aggregates):
                print(say("cli.ask.aggregates_list"))
                for index, title in enumerate(analysis.bundle.aggregates, 1):
                    print(f"  {index}. {title or say('cli.ask.aggregates_outside')}")
            return 0
        _validate(args, analysis, parser)
        selection = _selection(args, analysis, parser)
        output = args.output_dir or args.file.parent
        options = RenderOptions(folder_layout=args.folder_layout or "regular",
                                box_kind=args.box_kind or "auto", box_folders=args.box_folders != "omit")
        result = generate(analysis, output, labels=args.labels, selection=selection,
                          numbering_preference=args.numbering, first_folder=args.first_folder or 1,
                          render_options=options)
        report(analysis, result, output, args.labels)
    except SystemExit as exc:
        return int(exc.code or 0)
    except (InputError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0
