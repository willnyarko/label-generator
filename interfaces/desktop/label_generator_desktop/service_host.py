"""Run the label service on a loopback port for the desktop window.

The window is a view onto ``label_generator.service``. The interface it shows is
the asset that package ships, served here rather than reimplemented, which is why
this package contains no interface of its own.

The server here is bound to 127.0.0.1 on an ephemeral port. Nothing is exposed
beyond the machine, and no outbound request is made: label generation is entirely
local, including the collection identity the operator supplies for spreadsheets.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import threading
import time
from typing import Optional

from label_generator.content import say
from . import __version__, recovery


def pick_free_port(host: str = "127.0.0.1") -> int:
    """Ask the operating system for an unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


class ServiceHost:
    """A uvicorn server for the shared service, running on a background thread."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        *,
        feedback_url: Optional[str] = None,
        notice: Optional[str] = None,
        updater=None,
    ) -> None:
        """Choose where the service will listen; ``port=None`` takes any free port."""
        self.host = host
        self.port = port or pick_free_port(host)
        #: Rendered in the interface footer so that staff running a packaged
        #: copy have somewhere to report a defect.
        self.feedback_url = feedback_url
        #: One line shown above the interface. A packaged application has no
        #: visible standard output, so an update notice has to arrive this way.
        self.notice = notice
        #: Installs a newer build when the interface asks it to.
        self.updater = updater
        self._server = None
        self._thread: Optional[threading.Thread] = None
        #: When the interface last made a request; browser mode exits once it stops.
        self.last_request = time.monotonic()

    @property
    def base_url(self) -> str:
        """The address the window loads."""
        return f"http://{self.host}:{self.port}"

    def start(self, *, timeout: float = 20.0) -> str:
        """Start the server and return its base URL once it accepts requests."""
        import uvicorn

        from label_generator.service.app import create_app

        ready = os.environ.get(recovery.READY)

        def interface_opened():
            recovery.write_marker(Path(ready), __version__)

        # Inputs are local files. An explicit MAX_UPLOAD_BYTES still applies.
        app = create_app(feedback_url=self.feedback_url, notice=self.notice, updater=self.updater,
                         on_opened=interface_opened if ready else None, default_upload_bytes=0)

        async def tracked(scope, receive, send):
            """Note the time of every request so an idle service can be told from a busy one."""
            self.last_request = time.monotonic()
            await app(scope, receive, send)

        config = uvicorn.Config(
            tracked,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            use_colors=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run,
            name="label-generator-service",
            daemon=True,
        )
        self._thread.start()
        self._wait_until_started(timeout)
        return self.base_url

    def _wait_until_started(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if getattr(self._server, "started", False):
                return
            if self._thread is not None and not self._thread.is_alive():
                raise RuntimeError(say("desktop.service_stopped"))
            time.sleep(0.05)
        raise TimeoutError(say("desktop.service_slow", seconds=f"{timeout:.0f}"))

    def stop(self, *, timeout: float = 10.0) -> None:
        """Ask the server to exit and wait for its thread to finish."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._server = None
        self._thread = None

    def __enter__(self) -> "ServiceHost":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()
