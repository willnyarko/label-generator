"""Desktop surface: loopback service lifecycle and the optional update check.

These run headless. The native window is not exercised, but everything the
window depends on is: the service starts, serves the shared interface, and stops
cleanly, and the update check stays silent unless it is configured.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from label_generator_desktop import __version__, updates
from label_generator_desktop.app import build_parser, main
from label_generator_desktop.service_host import ServiceHost


def _get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8")


# ------------------------------------------------------------- service host


def test_service_starts_serves_and_stops() -> None:
    host = ServiceHost()
    url = host.start()
    try:
        assert url.startswith("http://127.0.0.1:")
        status, body = _get(f"{url}/health")
        assert status == 200
        assert json.loads(body)["status"] == "ok"
    finally:
        host.stop()


def test_service_serves_the_shared_interface() -> None:
    """The window must show the service's own interface, never a copy of its own."""
    from label_generator.service.app import render_interface

    with ServiceHost() as host:
        _status, body = _get(f"{host.base_url}/")
    assert body == render_interface()


def test_service_binds_only_to_loopback() -> None:
    with ServiceHost() as host:
        assert host.host == "127.0.0.1"
        assert host.base_url.startswith("http://127.0.0.1:")


def test_service_host_can_be_restarted_on_a_fresh_port() -> None:
    first = ServiceHost()
    first.start()
    first_port = first.port
    first.stop()

    second = ServiceHost()
    second.start()
    try:
        assert second.port != 0
        assert _get(f"{second.base_url}/health")[0] == 200
    finally:
        second.stop()
    assert first_port != 0


# ------------------------------------------------------------------ updates


@pytest.mark.parametrize(
    "lower,higher",
    [
        ("2.0.0", "2.0.1"),
        ("2.0.0", "2.1.0"),
        ("2.9.0", "10.0.0"),
        ("2.0", "2.0.1"),
    ],
)
def test_version_ordering(lower: str, higher: str) -> None:
    assert updates.version_tuple(lower) < updates.version_tuple(higher)


def test_version_tuple_tolerates_junk() -> None:
    assert updates.version_tuple("") == (0,)
    assert updates.version_tuple("v2.0.1-beta") == (2, 0, 1)


def _opener_for(payload: object):
    def opener(_url, timeout=None):  # noqa: ARG001 - signature mirrors urlopen
        class _Response:
            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        return _Response()

    return opener


def test_no_manifest_url_means_no_request_at_all(monkeypatch) -> None:
    monkeypatch.delenv(updates.MANIFEST_URL_ENV, raising=False)

    def explode(*_args, **_kwargs):
        raise AssertionError("an unconfigured update check must not open a connection")

    assert updates.check_for_updates("2.0.0", opener=explode) is None


def test_newer_version_is_reported() -> None:
    info = updates.check_for_updates(
        "2.0.0",
        url="https://example.invalid/latest.json",
        opener=_opener_for({"version": "2.1.0", "url": "https://example.invalid/download"}),
    )
    assert info is not None
    assert info.latest == "2.1.0"
    assert info.is_newer
    assert "2.1.0" in updates.describe(info)


def test_same_or_older_version_is_silent() -> None:
    for latest in ("2.0.0", "1.9.9"):
        assert (
            updates.check_for_updates(
                "2.0.0",
                url="https://example.invalid/latest.json",
                opener=_opener_for({"version": latest}),
            )
            is None
        )


def test_unreachable_host_is_silent() -> None:
    def fail(*_args, **_kwargs):
        raise OSError("network is unreachable")

    assert (
        updates.check_for_updates("2.0.0", url="https://example.invalid/latest.json", opener=fail)
        is None
    )


def test_malformed_manifest_is_silent() -> None:
    def opener(_url, timeout=None):  # noqa: ARG001
        class _Response:
            def read(self) -> bytes:
                return b"not json at all"

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        return _Response()

    assert (
        updates.check_for_updates("2.0.0", url="https://example.invalid/latest.json", opener=opener)
        is None
    )


def test_manifest_without_a_version_is_ignored() -> None:
    assert updates.parse_manifest({"url": "https://example.invalid"}, "2.0.0") is None
    assert updates.parse_manifest({}, "2.0.0") is None


def test_manifest_url_falls_back_to_the_environment(monkeypatch) -> None:
    monkeypatch.setenv(updates.MANIFEST_URL_ENV, "https://example.invalid/latest.json")
    assert updates.manifest_url() == "https://example.invalid/latest.json"
    assert updates.manifest_url("https://override.invalid") == "https://override.invalid"


def test_describe_is_empty_when_there_is_nothing_to_say() -> None:
    assert updates.describe(None) == ""


# --------------------------------------------------------------- arguments


def test_version_flag_exits_cleanly(capsys) -> None:
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_parser_defaults_are_safe() -> None:
    args = build_parser().parse_args([])
    assert args.browser is False
    assert args.port is None
    assert args.no_update_check is False


# ------------------------------------------------------- surface extras


def test_service_host_passes_feedback_and_notice_to_the_interface() -> None:
    host = ServiceHost(
        feedback_url="https://example.invalid/issues",
        notice="Version 2.1.0 is available.",
    )
    host.start()
    try:
        payload = json.loads(_get(f"{host.base_url}/api/config")[1])
    finally:
        host.stop()
    assert payload["feedback_url"] == "https://example.invalid/issues"
    assert payload["notice"] == "Version 2.1.0 is available."


def test_desktop_wording_in_content_toml_matches_the_code() -> None:
    """Every say("desktop.x") resolves, and every desktop.* string is used."""
    import re
    from pathlib import Path

    from label_generator.content import content

    asked = set()
    for py in (Path(__file__).parents[1] / "label_generator_desktop").glob("*.py"):
        asked |= set(re.findall(r'say\(\s*"(desktop\.\w+)"', py.read_text(encoding="utf-8")))
    have = {f"desktop." + k for k in content()["desktop"]}
    assert asked == have, (asked ^ have)
