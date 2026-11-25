"""The command-line front end and the program's starting point.

A user can start the program by double-clicking the executable file or, on Windows,
dropping a file onto it. The program lists likely files or starts from the given file.
It asks for whatever collection information the file leaves open, then shows the
label settings for review. The prompt lists the available keys, including q to quit
and b to go back where offered. The run writes the labels beside the selected file.

With explicit command arguments, the program uses the supplied settings and defaults.
This file passes answers to the pipeline and prints what was made along with any notes.
The reading, numbering, and writing all happen in other files.
"""

from __future__ import annotations

import contextlib
import filecmp
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
from readers import read_input
from readers.detect import recognised_kind
from repositories import repositories

__all__ = ["main"]

T = TypeVar("T")

RECENT_DAYS = 7  # how far back the Downloads folder is searched
MOST_LISTED = 9  # files offered at once, so each is one key
BOXES_PER_LINE = 10  # boxes shown on each line of the box list

BACK = object()  # the answer b: back to the question before
NEW_FILE = object()
EDIT = object()
QUIT = object()  # the answer q: stop without making anything

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
        analysis = self._reading(self.file, None, None, None)
        analysis.require_components()
        return analysis

    def analysis(self) -> AnalysisResult:
        return self._reading(self.file, self.collection, self.call_number, self.repository)

    def _reading(self, file, collection, call_number, repository) -> AnalysisResult:
        key = (file, collection, call_number, repository)
        if key not in self.readings:
            self.readings[key] = analyze(file, collection=collection, call_number=call_number, repository=repository)
        return self.readings[key]


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and (argv[0] == "run" or argv[0].startswith("-") or len(argv) > 1):
        from command import run_command
        return run_command(argv, _report)
    if not argv and not sys.stdin.isatty():
        print(say("cli.start.usage"))
        return 0
    run = _Run(file=Path(argv[0]) if argv else None, from_list=not argv)
    if not sys.stdin.isatty():
        try:
            _make_labels(run)
            return 0
        except (InputError, OSError) as exc:
            print(exc, file=sys.stderr)
            return 1
    if not argv:
        print(say("cli.start.welcome"))
    steps = START_STEPS
    while True:
        try:
            if _walk(steps, run) is QUIT:
                print(say("cli.after.quit"))
                return 0
            _make_labels(run)
        except InputError as exc:
            print(str(exc), file=sys.stderr, flush=True)
            choices = [(NEW_FILE, say("cli.after.choose")), (QUIT, say("cli.after.quit_choice"))]
            if exc.change_settings:
                choices.insert(0, (EDIT, say("cli.after.recover_settings")))
            action = _menu(say("cli.after.next"), choices, default=1, back=False, eof=QUIT)
            if action is QUIT:
                return 1
        except OSError as exc:
            print(say("cli.after.error", error=exc), file=sys.stderr)
            return 1
        else:
            action = _menu(say("cli.after.next"),
                           [(QUIT, say("cli.after.finish")), (EDIT, say("cli.after.edit")),
                            (NEW_FILE, say("cli.after.another"))], default=1, back=False)
            if action is QUIT:
                return 0
        if action is NEW_FILE:
            run = _Run(from_list=True)
            steps = START_STEPS
        else:
            steps = REVIEW_STEPS


def _walk(steps: list[Step], run: _Run, *, back_to_review: bool = False) -> object:
    asked: list[int] = []
    index = 0
    while index < len(steps):
        applies, ask = steps[index]
        if not applies(run):
            index += 1
            continue
        move = ask(run, bool(asked) or back_to_review)
        if move is QUIT:
            return QUIT
        if move is BACK:
            if not asked:
                return BACK
            index = asked.pop()
        else:
            asked.append(index)
            index += 1
    return None


def _make_labels(run: _Run) -> None:
    if run.from_list and not run.picked_other:
        run.file = _bring_here(run.file, _program_folder())  # the answers given stay with the copy
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
    elif labels == "boxes":  # a box-only run leaves the folders out, so a folder count would read 0
        print(say("cli.after.counts_boxes", boxes=boxes))
    else:
        print(say("cli.after.counts_both", folders=folders, boxes=boxes))
    print(say("cli.after.outputs_line", folder=output))
    for path in result.output_paths:
        print(f"  {path}")
    for note in result.notes:
        print("\n" + str(note))
    print("\n" + say("cli.after.done"))


# --- The questions, in the order a person meets them ------------------------------------------
# Each step is (applies, ask). ask records its answer on the run and returns None, or
# returns BACK or QUIT; the second argument says whether there is a question to go back to.


def _ask_file(run: _Run, back: bool) -> object:
    here = _program_folder()
    found = _likely_inputs(here, _downloads_folder())
    if not found:
        print("\n" + say("cli.start.files_none", days=RECENT_DAYS))
        run.picked_other = True
        return None
    options = [(path, _describe(path, here)) for path in found]
    options.append((None, say("cli.start.files_other")))
    choice = _menu(say("cli.start.files_menu"), options, back=back, eof=QUIT)
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
            return QUIT  # the keyboard closed before a file was named
        if typed is BACK or typed is QUIT:
            return typed
        if not typed:
            continue
        path = _as_path(typed)
        run.use_file(path)
        return None


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
        if typed is not None:
            setattr(run, name, typed or None)
    return None


def _ask_repository(run: _Run, back: bool) -> object:
    choices = [(repo.code, repo.display) for repo in repositories()]
    choices.append((None, say("cli.ask.repository_skip")))
    code = _menu(say("cli.ask.repository_menu"), choices, back=back, eof=None)
    if code is BACK or code is QUIT:
        return code
    run.repository = code
    return None


def _ask_scope(run: _Run, back: bool) -> object:
    options = [("all", say("cli.ask.scope_all")), ("boxes", say("cli.ask.scope_boxes"))]
    if any(run.analysis().bundle.aggregates):
        options.append(("aggregates", say("cli.ask.scope_aggregates")))
    scope = _menu(say("cli.ask.scope_menu"), options, default=_current(options, run.scope), back=back)
    if scope is BACK or scope is QUIT:
        return scope
    run.scope = scope
    if scope == "all":
        run.selection = Selection()
    return None


def _ask_boxes(run: _Run, back: bool) -> object:
    boxes = list(dict.fromkeys(box.box for box in run.analysis().bundle.boxes))
    lines = ["  " + ", ".join(boxes[i:i + BOXES_PER_LINE]) for i in range(0, len(boxes), BOXES_PER_LINE)]
    _display(say("cli.ask.boxes_list"), lines)
    while True:
        current = run.selection.typed if run.selection.scope == "boxes" else ""
        typed = _answer(say("cli.ask.boxes_ask"), back, current)
        if typed is None:  # the keyboard closed: the whole collection
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
    options = run.analysis().bundle.aggregates
    _display(say("cli.ask.aggregates_list"),
             [f"  {n}. {title or say('cli.ask.aggregates_outside')}" for n, title in enumerate(options, 1)])
    while True:
        current = run.selection.typed if run.selection.scope == "aggregates" else ""
        typed = _answer(say("cli.ask.aggregates_ask"), back, current)
        if typed is None:  # the keyboard closed: the whole collection
            run.scope, run.selection = "all", Selection()
            return None
        if typed is BACK or typed is QUIT:
            return typed
        numbers = read_numbers(typed, len(options))
        if numbers:
            run.selection = Selection("aggregates", aggregates=numbers, typed=typed)
            return None
        print(say("cli.ask.aggregates_invalid", count=len(options)))


def _setting(run: _Run, attr: str, question: str, options: list[tuple], back: bool) -> object:
    answer = _menu(question, options, default=_current(options, getattr(run, attr)), back=back)
    if answer is BACK or answer is QUIT:
        return answer
    setattr(run, attr, answer)
    return None


def _ask_labels(run: _Run, back: bool) -> object:
    return _setting(run, "labels", say("cli.ask.labels_menu"), [
        ("both", say("cli.ask.labels_both")), ("folders", say("cli.ask.labels_folders")),
        ("boxes", say("cli.ask.labels_boxes"))], back)


def _ask_box_folders(run: _Run, back: bool) -> object:
    return _setting(run, "box_folders", say("cli.ask.box_folders_menu"), [
        (True, say("cli.ask.box_folders_shown")), (False, say("cli.ask.box_folders_left_off"))], back)


def _ask_numbering(run: _Run, back: bool) -> object:
    return _setting(run, "numbering", say("cli.ask.numbering_menu"), [
        ("per-box", say("cli.ask.numbering_per_box")), ("through-collection", say("cli.ask.numbering_through"))], back)


def _ask_first_folder(run: _Run, back: bool) -> object:
    _display(say("cli.ask.first_folder"))
    while True:
        typed = _answer(say("cli.ask.input_hint"), back, str(run.first_folder))
        if typed is BACK or typed is QUIT:
            return typed
        if typed is None:
            return None
        if typed.isascii() and typed.isdecimal() and int(typed) > 0:
            run.first_folder = int(typed)
            return None
        print(say("cli.ask.first_folder_invalid"))


def _ask_layout(run: _Run, back: bool) -> object:
    return _setting(run, "layout", say("cli.ask.layout_menu"), [
        ("regular", say("cli.ask.layout_regular")), ("left", say("cli.ask.layout_left"))], back)


def _ask_box_kind(run: _Run, back: bool) -> object:
    return _setting(run, "box_kind", say("cli.ask.box_kind_menu"), [
        ("auto", say("cli.ask.box_kind_auto")), ("full", say("cli.ask.box_kind_full")),
        ("half-hollinger", say("cli.ask.box_kind_half")), ("flat", say("cli.ask.box_kind_flat"))], back)


def _review(run: _Run, back: bool) -> object:
    # Read the input before offering to write anything, including a default run.
    while True:
        choice = _menu(_summary(run), [(1, say("cli.ask.summary_make")), (2, say("cli.ask.summary_edit_labels")),
                                       (3, say("cli.ask.summary_edit_scope"))], default=1, back=back)
        if choice is BACK or choice is QUIT:
            return choice
        if choice == 1:
            return None
        edit_steps = LABEL_STEPS if choice == 2 else SCOPE_STEPS
        if _walk(edit_steps, run, back_to_review=True) is QUIT:
            return QUIT
        run.scope = run.selection.scope


def _summary(run: _Run) -> str:
    bundle = run.analysis().bundle
    labels = {
        "both": say("cli.ask.labels_both"),
        "folders": say("cli.ask.labels_folders"),
        "boxes": say("cli.ask.labels_boxes"),
    }[run.labels]
    outside = say("cli.ask.aggregates_outside")
    scope = {
        "all": say("cli.ask.scope_all"),
        "boxes": say("cli.ask.scope_boxes_named", typed=run.selection.typed),
        "aggregates": "; ".join(f"{n}. {bundle.aggregates[n-1] or outside}" for n in run.selection.aggregates),
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
        say("cli.ask.summary_heading", title=run.analysis().record.primary_title(), call_number=run.analysis().record.call_number()),
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
    return "\n".join(lines)


SCOPE_STEPS: list[Step] = [
    (lambda run: True, _ask_scope),
    (lambda run: run.scope == "boxes", _ask_boxes),
    (lambda run: run.scope == "aggregates", _ask_aggregates),
    (lambda run: _folders_printed(run) and run.analysis().numbering_required, _ask_numbering),
    (
        lambda run: _folders_printed(run)
        and run.numbering == "through-collection"
        and run.analysis().numbering_required
        and not run.analysis().bundle.stated_folders,
        _ask_first_folder,
    ),
]

LABEL_STEPS: list[Step] = [
    (lambda run: True, _ask_labels),
    (lambda run: run.labels != "folders", _ask_box_folders),
    (lambda run: run.labels != "boxes", _ask_layout),
    (lambda run: run.labels != "folders", _ask_box_kind),
]

REVIEW_STEPS: list[Step] = [(lambda run: True, _review)]
START_STEPS: list[Step] = [
    (lambda run: run.from_list, _ask_file),
    (lambda run: run.from_list and run.picked_other, _ask_path),
    (lambda run: run.as_found().record.identity_missing(), _ask_identity),
    (lambda run: run.as_found().record.repository is None, _ask_repository),
    *REVIEW_STEPS,
]


def _folders_printed(run: _Run) -> bool:
    return run.labels != "boxes" or run.box_folders


# --- Asking -------------------------------------------------------------------------------------


def _display(heading: str, choices: list[str] | None = None) -> None:
    print("\n" + "-" * 40)
    print(heading)
    if choices:
        print()
        print("\n".join(choices))
    print()


def _current(options: list[tuple], value: object) -> int:
    return next((i for i, (key, _) in enumerate(options, 1) if key == value), 1)


def _menu(question: str, options: list[tuple], *, default: int | None = None,
          back: bool = True, eof: object = ...) -> object:
    choices = [f"  {i}. {label}" + (say("cli.ask.default_mark") if i == default else "")
               for i, (_, label) in enumerate(options, 1)]
    _display(question, choices)
    count = len(options)
    key_range = f"1–{count}" if count > 1 else "1"
    while True:
        answer = _answer(say("cli.ask.number", range=key_range), back, str(default) if default else "")
        if answer is None:
            return options[(default or 1) - 1][0] if eof is ... else eof
        if answer is BACK or answer is QUIT:
            return answer
        if answer.isascii() and answer.isdecimal() and len(answer) < 12 and 1 <= int(answer) <= count:
            return options[int(answer) - 1][0]
        print(say("cli.ask.choose_invalid", count=count))


def _type(question: str, back: bool = True) -> object:
    _display(question)
    return _answer(say("cli.ask.input_hint"), back)


def _answer(prompt: str, back: bool, default: str = "") -> object:
    keys = [prompt]
    if default:
        keys.append(say("cli.ask.enter", choice=default))
    if back:
        keys.append(say("cli.ask.back"))
    keys.append(say("cli.ask.quit"))
    answer = _read(", ".join(keys) + " > ")
    if answer is None:
        return None
    return _move(answer, back) or answer or default


def _move(answer: str, back: bool) -> object:
    key = answer.strip().lower()
    if key == "q":
        return QUIT
    if key == "b" and back:
        return BACK
    return None


# --- Finding the file -----------------------------------------------------------------------------


def _program_folder() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


def _downloads_folder() -> Path:
    return Path.home() / "Downloads"


def _likely_inputs(here: Path, downloads: Path) -> list[Path]:
    since = time.time() - RECENT_DAYS * 86400
    found: dict[Path, tuple[Path, float]] = {}
    for folder, recent_only in ((here, False), (downloads, True)):
        with contextlib.suppress(OSError):
            for path in folder.iterdir():
                with contextlib.suppress(OSError):
                    if path.suffix.lower() not in {".xml", ".csv"}:
                        continue
                    modified = path.stat().st_mtime
                    if (not recent_only or modified >= since) and recognised_kind(path):
                        found.setdefault(path.resolve(), (path, modified))
    newest_first = sorted(found.values(), key=lambda item: item[1], reverse=True)
    return [path for path, _ in newest_first[:MOST_LISTED]]


def _describe(path: Path, here: Path) -> str:
    place = say("cli.start.files_here") if path.parent.resolve() == here.resolve() else say("cli.start.files_downloads")
    where = say("cli.start.files_where", name=path.name, place=place)
    if path.suffix.lower() == ".xml":
        title, number = _ead_identity(path)
        label = title or say("cli.start.files_ead")
    else:
        label, number = say("cli.start.files_sheet"), None
        with contextlib.suppress(InputError, OSError):
            record = read_input(path)
            if record.title_provenance != "absent":
                label = record.primary_title()
            if record.call_number_provenance != "absent":
                number = record.call_number()
    if number:
        label += f" ({number})"
    return f"{label} — {where}"


def _ead_identity(path: Path) -> tuple[Optional[str], Optional[str]]:
    from lxml import etree

    def local(el) -> str:
        return etree.QName(el).localname if el is not None else ""

    title = number = None
    with contextlib.suppress(Exception):
        for _, el in etree.iterparse(str(path), events=("end",), recover=True, huge_tree=True):
            parent = el.getparent()
            if local(el) == "did" and local(parent) == "archdesc":
                break  # the top-level description ends before the components begin
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
        index = 1
        while True:
            try:
                destination = copy.open("xb")
                break
            except FileExistsError:
                if copy.is_file() and filecmp.cmp(path, copy, shallow=False):
                    return copy
                index += 1
                copy = here / f"{path.stem} ({index}){path.suffix}"
        try:
            with destination, path.open("rb") as source:
                shutil.copyfileobj(source, destination)
        except OSError:
            copy.unlink(missing_ok=True)
            raise
    except OSError:
        return path
    with contextlib.suppress(OSError):
        stat = path.stat()
        os.utime(copy, (stat.st_atime, stat.st_mtime))  # keeps its date, so it stays in its place in the list
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


if __name__ == "__main__":
    raise SystemExit(main())
