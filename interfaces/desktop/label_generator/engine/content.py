"""Load the label engine’s wording from its bundled configuration."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

CONFIG = Path(__file__).with_name("config")


@cache
def content() -> dict:
    """The parsed ``content.toml``."""
    return tomllib.loads((CONFIG / "content.toml").read_text(encoding="utf-8"))


def say(key: str, **values: object) -> str:
    """The text at a dotted key such as ``ead_reason.not_ead``, placeholders filled."""
    node = content()
    for part in key.split("."):
        node = node[part]
    return node.format(**values)
