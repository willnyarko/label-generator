"""Looks up repositories for the labels in the Yale ArchivesSpace list at ``config/repositories.json``.

Resource URIs in the bulk import spreadsheets look like ``/repositories/{number}/resources/{number}``.
For example: /repositories/11/resources/12345
"""

from __future__ import annotations

import json
import re
from functools import cache
from typing import Optional

from content import CONFIG
from models.ycar import Repository


@cache
def _entries() -> list[dict]:
    return json.loads((CONFIG / "repositories.json").read_text(encoding="utf-8"))["repositories"]


def _repository(entry: dict) -> Repository:
    return Repository(code=entry["short"], display=entry["long"])


def repositories() -> list[Repository]:
    return [_repository(entry) for entry in _entries()]


def by_code(code: Optional[str]) -> Optional[Repository]:
    return next((r for r in repositories() if r.code == code), None)


def from_uri(uri: str) -> Optional[Repository]:
    match = re.search(r"/repositories/(\d+)", uri or "")
    entry = next((e for e in _entries() if match and e["number"] == match.group(1)), None)
    return _repository(entry) if entry else None
