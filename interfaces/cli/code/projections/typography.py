"""The font and type size of each kind of label, read from ``config/typography.toml``."""

from __future__ import annotations

import tomllib
from functools import cache

from content import CONFIG

CONFIG_FILE = CONFIG / "typography.toml"


@cache
def typography() -> dict:
    return tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
