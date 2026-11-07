from __future__ import annotations

import urllib.request
from typing import Any

import pytest

from notification_port.transport import UrllibNtfyTransport


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_send_propagates_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(OSError):
        UrllibNtfyTransport().send(urllib.request.Request("http://x"), timeout=1)


def test_is_healthy_only_for_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Response(200))
    assert UrllibNtfyTransport().is_healthy("http://x", timeout=1) is True
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Response(503))
    assert UrllibNtfyTransport().is_healthy("http://x", timeout=1) is False


def test_is_healthy_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert UrllibNtfyTransport().is_healthy("http://x", timeout=1) is False
