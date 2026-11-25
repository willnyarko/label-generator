"""Notices tell users what they need to know about a file.

Every notice has a number and a title, such as Note 302 — Placeholder box number.
The number tells which stage of the workflow produced it.

- 1NN: opening the file
- 2NN: reading the file
- 3NN: making the labels

The wording lives in config/content.toml. Under notices.<name>, you will find
information about what happened and what to do. Stop the run only when no useful
label could come out. Otherwise add a note and go on.
"""

from __future__ import annotations

from dataclasses import dataclass

from content import content, say
from models.lrr import LrrBundle, MISSING_BOX_SENTINEL
from models.ycar import YcarRecord


@dataclass(frozen=True)
class Notice:

    number: int
    name: str
    kind: str  # "error" stops the run, "note" comes with the labels
    title: str
    text: str
    fix: str

    @property
    def heading(self) -> str:
        kind = say("notice.error") if self.kind == "error" else say("notice.note")
        return say("notice.heading", kind=kind, number=self.number, title=self.title)

    def __str__(self) -> str:
        return "\n\n".join(part for part in (self.heading, self.text, self.fix) if part)


def notice(which: str, /, *, variant: str | None = None, **values: object) -> Notice:
    entry = content()["notices"][which]
    if variant:
        entry = entry | entry[variant]
    return Notice(
        number=entry["number"],
        name=which,
        kind=entry["kind"],
        title=entry["title"],
        text=entry["text"].format(**values),
        fix=entry["fix"].format(**values),
    )


class InputError(Exception):

    def __init__(self, which: str, /, *, change_settings: bool = False, **values: object):
        self.change_settings = change_settings
        self.notice = notice(which, **values)
        super().__init__(str(self.notice))


def label_notes(record: YcarRecord, bundle: LrrBundle) -> list[Notice]:
    """Notes to show with the labels actually generated for this selection."""
    notes: list[Notice] = []
    if any(row.placeholder_box for row in [*bundle.folders, *bundle.boxes]):
        notes.append(notice("missing-box", sentinel=MISSING_BOX_SENTINEL))
    if record.identity_missing():
        variant = None
        if record.title_provenance != "absent":
            variant = "call_number"
        elif record.call_number_provenance != "absent":
            variant = "collection"
        notes.append(notice("missing-identity", variant=variant))
    if bundle.boxes and record.repository is None:
        notes.append(notice("no-repository"))
    if record.replaced_characters:
        replaced = record.replaced_characters
        lines = list(dict.fromkeys(str(line) for line, _ in replaced))
        line_text = ", ".join(lines)
        if len(lines) > 1:
            line_text = (", ".join(lines[:-1]) + (", and " if len(lines) > 2 else " and ") + lines[-1])
        subject = say("replacement.one_subject") if len(replaced) == 1 else say("replacement.many_subject")
        location = say("replacement.one_line" if len(lines) == 1 else "replacement.multiple_lines", subject=subject, lines=line_text)
        notes.append(
            notice(
                "replaced-characters",
                count=len(replaced),
                characters=", ".join(dict.fromkeys(f"U+{ord(ch):04X}" for _, ch in replaced)),
                character_word=say("replacement.singular") if len(replaced) == 1 else say("replacement.plural"),
                location=location,
            )
        )

    return notes
