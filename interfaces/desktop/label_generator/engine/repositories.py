"""Looks up repositories for the labels in the Yale ArchivesSpace list at ``config/repositories.json``.

Resource URIs in the bulk import spreadsheets look like ``/repositories/{number}/resources/{number}``.
For example: /repositories/11/resources/12345

A spreadsheet's resource URI names its repository by number, and this list turns that
number into the name a reader sees. When a file names no repository, a user picks one
from this list. An EAD file names its repository in words, and that name is used as the
EAD gives it. When a name changes or two repositories merge, we edit the JSON file.
"""

from __future__ import annotations

import json
import re
from functools import cache
from typing import Optional

from label_generator.engine.content import CONFIG
from label_generator.engine.models.ycar import Repository


@cache
def _entries() -> list[dict]:
    return json.loads((CONFIG / "repositories.json").read_text(encoding="utf-8"))["repositories"]


def _repository(entry: dict) -> Repository:
    return Repository(code=entry["short"], display=entry["long"])


def repositories() -> list[Repository]:
    """Every known repository, in the order a person is offered them."""
    return [_repository(entry) for entry in _entries()]


def by_code(code: Optional[str]) -> Optional[Repository]:
    """The repository with this short name, such as ``BRBL``."""
    return next((r for r in repositories() if r.code == code), None)


def from_uri(uri: str) -> Optional[Repository]:
    """The repository a resource URI such as ``/repositories/11/resources/13862`` points at."""
    match = re.search(r"/repositories/(\d+)", uri or "")
    entry = next((e for e in _entries() if match and e["number"] == match.group(1)), None)
    return _repository(entry) if entry else None
