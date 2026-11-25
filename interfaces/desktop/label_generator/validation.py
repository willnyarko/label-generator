"""Findings and recovery guidance shown by the desktop app."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .engine.notices import Notice
from .content import say

SUPPORTED_SUFFIXES = {".xml", ".csv"}


@dataclass(frozen=True)
class Finding:
    """A code, its message and recovery guidance, and an optional display heading."""

    code: str
    message: str
    fix: str
    heading: str = ""

    def __str__(self) -> str:
        if self.heading:
            return "\n\n".join((self.heading, self.message, self.fix))
        return say("finding.text", code=self.code, message=self.message, fix=self.fix)

    def to_dict(self) -> dict[str, str]:
        """The finding as plain data for a surface to show."""
        data = {"code": self.code, "message": self.message, "fix": self.fix}
        if self.heading:
            data["heading"] = self.heading
        return data


def finding(key: str, **values: object) -> Finding:
    """Build the finding for ``validation.<key>`` in content.toml."""
    base = f"validation.{key}"
    return Finding(
        say(f"{base}.code"),
        say(f"{base}.message", **values),
        say(f"{base}.fix", **values),
    )


class ValidationError(Exception):
    """A finding that stops the run."""

    def __init__(self, key: str | Notice | Finding, **values: object):
        if isinstance(key, Finding):
            self.finding = key
        elif isinstance(key, Notice):
            self.finding = Finding(str(key.number), key.text, key.fix, heading=key.heading)
        else:
            self.finding = finding(key, **values)
        self.code = self.finding.code
        super().__init__(str(self.finding))

    def to_dict(self) -> dict[str, str]:
        """The finding that stopped the run, as plain data."""
        return self.finding.to_dict()


def preflight(path: Path) -> None:
    """Refuse an input that cannot be processed at all."""
    if not path.is_file():
        raise ValidationError("not_a_file", path=path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValidationError("unsupported_type", name=path.name)
    try:
        with path.open("rb") as handle:
            first_byte = handle.read(1)
    except OSError as exc:
        raise ValidationError("unreadable", path=path, reason=exc.strerror or exc) from exc
    if not first_byte:
        # Left alone, an empty file fails later as "no labelable rows", which
        # sends staff looking for missing containers in a file with no content.
        raise ValidationError("empty_file", path=path)
