"""Literal text the program shows in the UI.

This project tries not to hardcode literal text to display inside the implementation code. Instead, it looks up a dotted key in ``config/content.toml`` and supplies the values for the ``{placeholders}``. This TOML file opens with a map of its sections and the modules that read them. If we want to make any UI text edits, all we have to do is edit the TOML file.
"""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

CONFIG = Path(__file__).with_name("config")


@cache
def content() -> dict:
    return tomllib.loads((CONFIG / "content.toml").read_text(encoding="utf-8"))


def say(key: str, **values: object) -> str:
    node = content()
    for part in key.split("."):
        node = node[part]
    return node.format(**values)
