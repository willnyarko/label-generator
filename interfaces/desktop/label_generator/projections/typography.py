"""Desktop-only proof settings. The label fonts and sizes live in the shared engine."""

from functools import cache
from pathlib import Path
import tomllib

from ..engine.projections.typography import typography

__all__ = ["typography", "proof_settings"]

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "typography.toml"


@cache
def proof_settings() -> dict:
    return tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))["proof"]
