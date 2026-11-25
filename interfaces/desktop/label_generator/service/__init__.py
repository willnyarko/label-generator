"""HTTP service and browser interface over the label pipeline.

A thin layer: every request goes through ``pipeline.analyze()`` and
``pipeline.generate()``, so the service adds no label logic of its own.
"""

from .app import app, create_app

__all__ = ["app", "create_app"]
