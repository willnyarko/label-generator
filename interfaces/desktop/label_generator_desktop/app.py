"""Desktop application entry point.

A native window over the browser interface. The window is the only thing this
package adds: the interface, the API and the label pipeline all come from the
``label_generator`` package beside it, so what a given input produces is decided
there.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from typing import Optional

from pathlib import Path

from label_generator.content import add as add_content, say

from . import __version__, recovery
from .service_host import ServiceHost
from .updates import check_for_updates, describe, find_install, make_updater

add_content(Path(__file__).with_name("config") / "content.toml")

WINDOW_TITLE = say("desktop.title")
WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 820
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 640

#: Where a "report a problem" link in the interface footer should point. The
#: packaged launchers set it; unset, no link is shown.
FEEDBACK_URL_ENV = "LABEL_GENERATOR_FEEDBACK_URL"

#: Browser mode has no window to close, so it ends once the page stops calling in.
#: The interface calls /health every 30 seconds while it is open.
BROWSER_IDLE_EXIT_SECONDS = 120

#: Set when an installed update asks the application to close so it can be replaced.
_exit_requested = threading.Event()


def request_exit() -> None:
    """Close the window, or end browser mode, shortly after an update is installed."""
    time.sleep(1.5)  # long enough for the interface to show that it is restarting
    _exit_requested.set()
    try:
        import webview

        for window in list(webview.windows):
            window.destroy()
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    """The desktop launcher's few options."""
    parser = argparse.ArgumentParser(
        prog="label-generator-desktop",
        description=say("desktop.description"),
    )
    parser.add_argument("--browser", action="store_true", help=say("desktop.browser"))
    parser.add_argument("--port", type=int, default=None, help=say("desktop.port"))
    parser.add_argument("--no-update-check", action="store_true", help=say("desktop.no_update_check"))
    parser.add_argument("--update-url", default=None, help=say("desktop.update_url"))
    parser.add_argument("--feedback-url", default=None, help=say("desktop.feedback_url"))
    parser.add_argument("--version", action="store_true", help=say("desktop.version"))
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    # pythonw.exe, which the Windows launcher uses, provides no standard streams,
    # and the server's logging cannot be configured without them.
    """Start the service, open the window, and stop the service when the window closes."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            # Kept open for the life of the process, which is why there is no `with`.
            setattr(sys, name, open(os.devnull, "w"))  # noqa: SIM115

    args = build_parser().parse_args(argv)

    if args.version:
        print(say("desktop.version_line", title=WINDOW_TITLE, version=__version__))
        return 0

    _exit_requested.clear()
    info = None
    if not args.no_update_check:
        install = find_install()
        info = check_for_updates(
            __version__, url=args.update_url, target=install.target if install else ""
        )
    notice = describe(info)
    if os.environ.get(recovery.RESTORED):
        notice = " ".join(filter(None, (say("desktop.update_restored", version=__version__), notice)))
    if notice:
        print(notice)

    host = ServiceHost(
        port=args.port,
        feedback_url=args.feedback_url or os.environ.get(FEEDBACK_URL_ENV) or None,
        notice=notice or None,
        updater=make_updater(info, on_ready=request_exit),
    )
    try:
        url = host.start()
    except (RuntimeError, TimeoutError) as exc:
        print(say("desktop.error", error=exc), file=sys.stderr)
        return 1
    except ImportError:
        print(say("desktop.service_missing"), file=sys.stderr)
        return 1

    try:
        if args.browser or not _run_in_window(url):
            _run_in_browser(host)
        return recovery.RESTART if _exit_requested.is_set() else 0
    finally:
        host.stop()


def _run_in_window(url: str) -> bool:
    """Show the native window. Returns False when no window could be shown."""
    try:
        import webview

        # Generated labels are downloads; the window refuses them unless told otherwise.
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(
            WINDOW_TITLE,
            url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
        )
        # On Windows, insist on WebView2: the older fallback engine cannot run the interface.
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)
        return True
    except Exception as exc:
        print(say("desktop.window_failed", reason=exc), file=sys.stderr)
        return False


def _run_in_browser(host: ServiceHost) -> None:
    """Open the interface in the default browser and run until the page is closed."""
    print(say("desktop.browser_running", title=WINDOW_TITLE, url=host.base_url))
    webbrowser.open(host.base_url)
    try:
        while (not _exit_requested.is_set()
               and time.monotonic() - host.last_request < BROWSER_IDLE_EXIT_SECONDS):
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
