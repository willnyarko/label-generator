"""Notices tell users what they need to know about a file: an error stops the program's run, and noteworthy information that wouldn't stop the run, but a user must know.

Every notice has a number and a name, such as 302 (missing-box). The number part follows the pattern:

- 1NN: noteworthy information occurring during the stage of opening the file
- 2NN: noteworthy information occurring during the stage of reading the file, and
- 3NN: noteworthy information occurring during the stage of making the label.

The name simply says what happened, and its wording lives in ``config/content.toml``. In this TOML file under ``notices.<name>``, you will find information about what happened and what to do, so that end users and maintainers can act on it.

Developer Rule of thumb for adding a notice: stop the run only when no useful label could come out; otherwise add a note and go on.
"""

from __future__ import annotations

from dataclasses import dataclass

from content import content, say


@dataclass(frozen=True)
class Notice:
    number: int
    name: str
    kind: str
    text: str
    fix: str

    def __str__(self) -> str:
        kind = say("notice.error") if self.kind == "error" else say("notice.note")
        return say("notice.text", kind=kind, number=self.number, name=self.name, text=self.text, fix=self.fix)


def notice(which: str, /, **values: object) -> Notice:
    entry = content()["notices"][which]
    return Notice(
        number=entry["number"],
        name=which,
        kind=entry["kind"],
        text=say(f"notices.{which}.text", **values),
        fix=say(f"notices.{which}.fix", **values),
    )


class InputError(Exception):
    def __init__(self, which: str, /, **values: object):
        self.notice = notice(which, **values)
        super().__init__(str(self.notice))
