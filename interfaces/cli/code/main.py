"""The command-line front end and the program's starting point.

A user can start the program by double-clicking the executable file, or if they use Windows, dropping a file onto the program. When the program starts, it either:
(1) lists the likely files and asks which one to work on, or
(2) when given a file, starts from that file.

Either way it then asks for whatever the file leaves open (for a spreadsheet, the collection name and call number), offers to go with the usual choices or to ask one numbered menu at a time, and writes the labels beside the file. Without someone at the keyboard it takes the default answer to every menu. Every menu presents a way for user to quit `q`, and after the first one, to go back `b`.

This file passes answers to the pipeline, and prints what was made along with any notes. The reading, numbering, and writing all happen in other files.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import sys
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable, Optional, TypeVar

from content import say
from lrr.selection import Selection, read_boxes, read_numbers
from notices import InputError
from pipeline import AnalysisResult, PipelineResult, analyze, generate
from projections.options import RenderOptions
from readers.detect import recognised_kind
from repositories import repositories

__all__ = ["main"]

T = TypeVar("T")

RECENT_DAYS = 7
MOST_LISTED = 9
BOXES_PER_LINE = 10

BACK = object()
QUIT = object()

Step = tuple[Callable[["_Run"], bool], Callable[["_Run", bool], object]]


@dataclass
class _Run:
    file: Optional[Path] = None
    from_list: bool = False
    picked_other: bool = False
    collection: Optional[str] = None
    call_number: Optional[str] = None
    repository: Optional[str] = None
    scope: str = "all"
    selection: Selection = field(default_factory=Selection)
    labels: str = "both"
    usual: bool = True
    box_folders: bool = True
    numbering: Optional[str] = None
    first_folder: int = 1
    layout: str = "regular"
    box_kind: str = "auto"
    readings: dict = field(default_factory=dict)

    def use_file(self, file: Optional[Path]) -> None:
        if file != self.file:
            for f in fields(self):
                if f.name not in ("from_list", "picked_other", "readings"):
                    setattr(self, f.name, f.default_factory() if callable(f.default_factory) else f.default)
        self.file = file

    def as_found(self) -> AnalysisResult:
        return self._reading(self.file, None, None, None)

    def analysis(self) -> AnalysisResult:
        return self._reading(self.file, self.collection, self.call_number, self.repository)

    def _reading(self, file, collection, call_number, repository) -> AnalysisResult:
        key = (file, collection, call_number, repository)
        if key not in self.readings:
            self.readings[key] = analyze(file, collection=collection, call_number=call_number, repository=repository)
        return self.readings[key]


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    interactive = sys.stdin.isatty()
    if (argv and argv[0].startswith("-")) or (not argv and not interactive):
        print(say("cli.start.usage"))
        return 0
    run = _Run(from_list=not argv)
    if argv:
        run.use_file(Path(argv[0]))
    else:
        print(say("cli.start.welcome"))

    code = _run(run, interactive)
    if getattr(sys, "frozen", False) and interactive and (run.from_list or _console_of_its_own()):
        with contextlib.suppress(EOFError):
            input("\n" + say("cli.after.pause"))
    return code


def _run(run: _Run, interactive: bool) -> int:
    try:
        if interactive and not _walk(STEPS, run):
            print("\n" + say("cli.after.quit"))
            return 0
        _make_labels(run)
        return 0
    except InputError as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception as exc:
        print(say("cli.after.error", error=exc), file=sys.stderr)
        return 1


def _walk(steps: list[Step], run: _Run) -> bool:
    asked: list[int] = []
    index = 0
    while index < len(steps):
        applies, ask = steps[index]
        if not applies(run):
            index += 1
            continue
        move = ask(run, bool(asked))
        if move is QUIT:
            return False
        if move is BACK:
            index = asked.pop()
            continue
        asked.append(index)
        index += 1
    return True


def _make_labels(run: _Run) -> None:
    if run.from_list and not run.picked_other:
        run.file = _bring_here(run.file, _program_folder())
    analysis = run.analysis()
    output = run.file.parent
    result = generate(
        analysis,
        output,
        labels=run.labels,
        selection=run.selection,
        numbering_preference=run.numbering,
        first_folder=run.first_folder,
        render_options=RenderOptions(folder_layout=run.layout, box_kind=run.box_kind, box_folders=run.box_folders),
    )
    _report(analysis, result, output, run.labels)


def _report(analysis: AnalysisResult, result: PipelineResult, output: Path, labels: str) -> None:
    print()
    print(say("cli.after.collection_line", title=analysis.record.primary_title(), call_number=analysis.record.call_number()))
    folders, boxes = len(result.bundle.folders), len(result.bundle.boxes)
    if labels == "folders":
        print(say("cli.after.counts_folders", folders=folders))
    elif labels == "boxes":
        print(say("cli.after.counts_boxes", boxes=boxes))
    else:
        print(say("cli.after.counts_both", folders=folders, boxes=boxes))
    print(say("cli.after.outputs_line", folder=output))
    for path in result.output_paths:
        print(f"  {path}")
    for note in result.notes:
        print("\n" + str(note))
    print("\n" + say("cli.after.done"))


def _ask_file(run: _Run, back: bool) -> object:
    here = _program_folder()
    found = _likely_inputs(here, _downloads_folder())
    if not found:
        print("\n" + say("cli.start.files_none", days=RECENT_DAYS))
        run.picked_other = True
        return None
    lines = [say("cli.start.files_menu")]
    lines += [f"  {number}. {_describe(path, here)}" for number, path in enumerate(found, start=1)]
    lines.append(f"  {len(found) + 1}. " + say("cli.start.files_other"))
    choice = _choose("\n".join(lines), [*found, None], back=back)
    if choice is BACK or choice is QUIT:
        return choice
    run.picked_other = choice is None
    if choice is not None:
        run.use_file(choice)
    return None


def _ask_path(run: _Run, back: bool) -> object:
    while True:
        typed = _type(say("cli.start.ask_file"), back)
        if typed is None:
            return QUIT
        if typed is BACK or typed is QUIT:
            return typed
        if not typed:
            continue
        path = _as_path(typed)
        if path.is_file():
            run.use_file(path)
            return None
        print(say("cli.start.file_missing", path=path))


def _ask_identity(run: _Run, back: bool) -> object:
    record = run.as_found().record
    for name, provenance, prompt in (
        ("collection", record.title_provenance, say("cli.ask.identity_collection")),
        ("call_number", record.call_number_provenance, say("cli.ask.identity_call_number")),
    ):
        if provenance != "absent":
            continue
        typed = _type(prompt, back)
        if typed is BACK or typed is QUIT:
            return typed
        if typed:
            setattr(run, name, typed)
    return None


def _ask_repository(run: _Run, back: bool) -> object:
    choices = repositories()
    lines = [say("cli.ask.repository_menu")]
    lines += [f"  {number}. {repo.display}" for number, repo in enumerate(choices, start=1)]
    code = _choose("\n".join(lines), [repo.code for repo in choices], back=back)
    if code is BACK or code is QUIT:
        return code
    run.repository = code
    return None


def _ask_usual(run: _Run, back: bool) -> object:
    usual = _choose(say("cli.ask.usual_menu"), [True, False], default=1, back=back)
    if usual is BACK or usual is QUIT:
        return usual
    run.usual = usual
    return None


def _ask_scope(run: _Run, back: bool) -> object:
    options = [("all", say("cli.ask.scope_all")), ("boxes", say("cli.ask.scope_boxes"))]
    if any(run.analysis().bundle.aggregates):
        options.append(("aggregates", say("cli.ask.scope_aggregates")))
    lines = [say("cli.ask.scope_menu")]
    lines += [f"  {number}. {text}" for number, (_, text) in enumerate(options, start=1)]
    scope = _choose("\n".join(lines), [value for value, _ in options], default=1, back=back)
    if scope is BACK or scope is QUIT:
        return scope
    run.scope = scope
    if scope == "all":
        run.selection = Selection()
    return None


def _ask_boxes(run: _Run, back: bool) -> object:
    boxes = [box.box for box in run.analysis().bundle.boxes]
    print("\n" + say("cli.ask.boxes_list"))
    for start in range(0, len(boxes), BOXES_PER_LINE):
        print("  " + ", ".join(boxes[start : start + BOXES_PER_LINE]))
    while True:
        typed = _type(say("cli.ask.boxes_ask"), back)
        if typed is None:
            run.scope, run.selection = "all", Selection()
            return None
        if typed is BACK or typed is QUIT:
            return typed
        chosen = read_boxes(typed, boxes)
        if chosen:
            run.selection = Selection("boxes", boxes=chosen, typed=typed)
            return None
        print(say("cli.ask.boxes_invalid"))


def _ask_aggregates(run: _Run, back: bool) -> object:
    paths = run.analysis().bundle.aggregates
    print("\n" + say("cli.ask.aggregates_list"))
    for number, path in enumerate(paths, start=1):
        title = path[-1] if path else say("cli.ask.aggregates_outside")
        print(f"  {number}. " + "   " * max(len(path) - 1, 0) + title)
    while True:
        typed = _type(say("cli.ask.aggregates_ask"), back)
        if typed is None:
            run.scope, run.selection = "all", Selection()
            return None
        if typed is BACK or typed is QUIT:
            return typed
        numbers = read_numbers(typed, len(paths))
        if numbers:
            run.selection = Selection("aggregates", aggregates=tuple(paths[n - 1] for n in numbers), typed=typed)
            return None
        print(say("cli.ask.aggregates_invalid", count=len(paths)))


def _ask_labels(run: _Run, back: bool) -> object:
    labels = _choose(say("cli.ask.labels_menu"), ["both", "folders", "boxes"], default=1, back=back)
    if labels is BACK or labels is QUIT:
        return labels
    run.labels = labels
    return None


def _ask_box_folders(run: _Run, back: bool) -> object:
    shown = _choose(say("cli.ask.box_folders_menu"), [True, False], default=1, back=back)
    if shown is BACK or shown is QUIT:
        return shown
    run.box_folders = shown
    return None


def _ask_numbering(run: _Run, back: bool) -> object:
    numbering = _choose(say("cli.ask.numbering_menu"), ["per-box", "through-collection"], default=1, back=back)
    if numbering is BACK or numbering is QUIT:
        return numbering
    run.numbering = numbering
    return None


def _ask_first_folder(run: _Run, back: bool) -> object:
    while True:
        typed = _type(say("cli.ask.first_folder"), back)
        if typed is BACK or typed is QUIT:
            return typed
        if not typed:
            run.first_folder = 1
            return None
        if typed.isdigit() and int(typed) > 0:
            run.first_folder = int(typed)
            return None
        print(say("cli.ask.first_folder_invalid"))


def _ask_layout(run: _Run, back: bool) -> object:
    layout = _choose(say("cli.ask.layout_menu"), ["regular", "left"], default=1, back=back)
    if layout is BACK or layout is QUIT:
        return layout
    run.layout = layout
    return None


def _ask_box_kind(run: _Run, back: bool) -> object:
    kind = _choose(say("cli.ask.box_kind_menu"), ["auto", "full", "half-hollinger", "flat"], back=back)
    if kind is BACK or kind is QUIT:
        return kind
    run.box_kind = kind
    return None


def _ask_to_make(run: _Run, back: bool) -> object:
    made = _choose(_summary(run), [True], default=1, back=back)
    return made if made is BACK or made is QUIT else None


def _summary(run: _Run) -> str:
    bundle = run.analysis().bundle
    labels = {
        "both": say("cli.ask.labels_both"),
        "folders": say("cli.ask.labels_folders"),
        "boxes": say("cli.ask.labels_boxes"),
    }[run.labels]
    outside = say("cli.ask.aggregates_outside")
    scope = {
        "all": say("cli.ask.scope_all_named"),
        "boxes": say("cli.ask.scope_boxes_named", typed=run.selection.typed),
        "aggregates": say(
            "cli.ask.scope_aggregates_named",
            titles="; ".join(path[-1] if path else outside for path in run.selection.aggregates),
        ),
    }[run.selection.scope]
    if bundle.stated_scheme:
        numbering = say("cli.ask.numbering_stated")
    elif run.numbering == "through-collection" and not bundle.stated_folders:
        numbering = say("cli.ask.numbering_through_from", first=run.first_folder)
    elif run.numbering == "through-collection":
        numbering = say("cli.ask.numbering_through")
    else:
        numbering = say("cli.ask.numbering_per_box")
    lines = [
        say("cli.ask.summary_heading"),
        say("cli.ask.summary_file", name=run.file.name),
        say("cli.ask.summary_labels", labels=labels),
        say("cli.ask.summary_scope", scope=scope),
    ]
    if _folders_printed(run):
        lines.append(say("cli.ask.summary_numbering", numbering=numbering))
    if run.labels != "boxes":
        layout = {"regular": say("cli.ask.layout_regular"), "left": say("cli.ask.layout_left")}[run.layout]
        lines.append(say("cli.ask.summary_layout", layout=layout))
    if run.labels != "folders":
        lines.append(
            say("cli.ask.summary_box_folders", folders=say("cli.ask.box_folders_shown") if run.box_folders else say("cli.ask.box_folders_left_off"))
        )
        kind = {
            "auto": say("cli.ask.box_kind_auto"),
            "full": say("cli.ask.box_kind_full"),
            "half-hollinger": say("cli.ask.box_kind_half"),
            "flat": say("cli.ask.box_kind_flat"),
        }[run.box_kind]
        lines.append(say("cli.ask.summary_box_kind", kind=kind))
    lines.append(say("cli.ask.summary_make"))
    return "\n".join(lines)


CHOICES: list[Step] = [
    (lambda run: True, _ask_scope),
    (lambda run: run.scope == "boxes", _ask_boxes),
    (lambda run: run.scope == "aggregates", _ask_aggregates),
    (lambda run: True, _ask_labels),
    (lambda run: run.labels != "folders", _ask_box_folders),
    (lambda run: _folders_printed(run) and run.analysis().numbering_required, _ask_numbering),
    (
        lambda run: _folders_printed(run)
        and run.numbering == "through-collection"
        and run.analysis().numbering_required
        and not run.analysis().bundle.stated_folders,
        _ask_first_folder,
    ),
    (lambda run: run.labels != "boxes", _ask_layout),
    (lambda run: run.labels != "folders", _ask_box_kind),
    (lambda run: True, _ask_to_make),
]

STEPS: list[Step] = [
    (lambda run: run.from_list, _ask_file),
    (lambda run: run.from_list and run.picked_other, _ask_path),
    (lambda run: run.as_found().record.identity_missing(), _ask_identity),
    (lambda run: run.as_found().record.repository is None, _ask_repository),
    (lambda run: True, _ask_usual),
    *((lambda run, applies=applies: not run.usual and applies(run), ask) for applies, ask in CHOICES),
]


def _folders_printed(run: _Run) -> bool:
    return run.labels != "boxes" or run.box_folders


def _choose(menu: str, values: list[T], *, default: Optional[int] = None, back: bool = True) -> object:
    print("\n" + menu)
    print(say("cli.ask.keys") if back else say("cli.ask.keys_quit"))
    ask = say("cli.ask.choose_default") if default else say("cli.ask.choose")
    while True:
        answer = _read(ask)
        if answer is None:
            return values[(default or 1) - 1]
        move = _move(answer, back)
        if move is not None:
            return move
        if not answer and default:
            return values[default - 1]
        if answer.isdigit() and 1 <= int(answer) <= len(values):
            return values[int(answer) - 1]
        print(say("cli.ask.choose_invalid", count=len(values)))


def _type(prompt: str, back: bool = True) -> object:
    print(say("cli.ask.keys") if back else say("cli.ask.keys_quit"))
    answer = _read(prompt)
    if answer is None:
        return None
    move = _move(answer, back)
    return answer if move is None else move


def _move(answer: str, back: bool) -> object:
    key = answer.strip().lower()
    if key == "q":
        return QUIT
    if key == "b" and back:
        return BACK
    return None


def _program_folder() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


def _downloads_folder() -> Path:
    return Path.home() / "Downloads"


def _likely_inputs(here: Path, downloads: Path) -> list[Path]:
    since = time.time() - RECENT_DAYS * 86400
    found: dict[Path, Path] = {}
    for folder, recent_only in ((here, False), (downloads, True)):
        with contextlib.suppress(OSError):
            for path in folder.iterdir():
                if recent_only and path.stat().st_mtime < since:
                    continue
                if recognised_kind(path):
                    found.setdefault(path.resolve(), path)
    newest_first = sorted(found.values(), key=lambda path: path.stat().st_mtime, reverse=True)
    return newest_first[:MOST_LISTED]


def _describe(path: Path, here: Path) -> str:
    place = say("cli.start.files_here") if path.parent.resolve() == here.resolve() else say("cli.start.files_downloads")
    where = say("cli.start.files_where", name=path.name, place=place)
    title, number = _ead_identity(path) if recognised_kind(path) == "ead" else (None, None)
    if title:
        return f"{title}, {number} {where}" if number else f"{title} {where}"
    return say("cli.start.files_sheet", where=where)


def _ead_identity(path: Path) -> tuple[Optional[str], Optional[str]]:
    from lxml import etree

    def local(el) -> str:
        return etree.QName(el).localname if el is not None else ""

    title = number = None
    with contextlib.suppress(Exception):
        for _, el in etree.iterparse(str(path), events=("end",), recover=True, huge_tree=True):
            parent = el.getparent()
            if local(el) == "did" and local(parent) == "archdesc":
                break
            if local(parent) != "did" or local(parent.getparent()) != "archdesc":
                continue
            text = " ".join("".join(el.itertext()).split())
            if local(el) == "unittitle" and title is None:
                title = text
            elif local(el) == "unitid" and number is None and el.get("audience") != "internal":
                number = text or None
    return title or None, number


def _bring_here(path: Path, here: Path) -> Path:
    if path.parent.resolve() == here.resolve():
        return path
    copy = here / path.name
    try:
        shutil.copyfile(path, copy)
    except OSError:
        return path
    with contextlib.suppress(OSError):
        stat = path.stat()
        os.utime(copy, (stat.st_atime, stat.st_mtime))
    return copy


def _as_path(typed: str) -> Path:
    try:
        words = shlex.split(typed, posix=os.name != "nt")
    except ValueError:
        words = [typed]
    text = words[0] if len(words) == 1 else typed
    return Path(text.strip("\"'")).expanduser()


def _read(prompt: str) -> Optional[str]:
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def _console_of_its_own() -> bool:
    if os.name != "nt":
        return False
    import ctypes

    return ctypes.windll.kernel32.GetConsoleProcessList((ctypes.c_uint * 4)(), 4) in (1, 2)


if __name__ == "__main__":
    raise SystemExit(main())
