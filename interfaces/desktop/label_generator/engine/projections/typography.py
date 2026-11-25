"""The font and type size of each kind of label, read from ``config/typography.toml``."""

from __future__ import annotations

import tomllib
from functools import cache

from label_generator.engine.content import CONFIG

CONFIG_FILE = CONFIG / "typography.toml"


@cache
def typography() -> dict:
    """``{"folder": {"font", "size"}, "box": {kind: {"font", "size"}}}``, parsed once."""
    return tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
