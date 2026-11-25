"""Load wording for previews, the application window and update messages."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

CONFIG = Path(__file__).with_name("config")
_FILES = [CONFIG / "content.toml"]


def add(path: Path) -> None:
    """Make another file's sections available to ``say``."""
    if path not in _FILES:
        _FILES.append(path)
        content.cache_clear()


@cache
def content() -> dict:
    """Every registered file, merged. Two files may not define the same section."""
    merged: dict = {}
    for path in _FILES:
        for section, table in tomllib.loads(path.read_text(encoding="utf-8")).items():
            if section in merged:
                raise ValueError(f"Section [{section}] is defined twice, the second time in {path}")
            merged[section] = table
    return merged


def say(key: str, **values: object) -> str:
    """The text at a dotted key such as ``ead_reason.not_ead``, placeholders filled."""
    node = content()
    for part in key.split("."):
        node = node[part]
    return node.format(**values)
