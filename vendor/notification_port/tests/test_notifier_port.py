from __future__ import annotations

from notification_port import Notifier, NotifyResult


def test_only_delivered_is_truthy() -> None:
    assert {r: bool(r) for r in NotifyResult} == {
        NotifyResult.DELIVERED: True,
        NotifyResult.UNCONFIGURED: False,
        NotifyResult.SPOOLED: False,
        NotifyResult.FAILED: False,
        NotifyResult.SKIPPED: False,
    }


class _Fake:
    def push(
        self, title: str, body: str, *, priority: str = "default", tags: str = "",
        click: str | None = None, actions: list[dict[str, object]] | None = None,
    ) -> NotifyResult:
        return NotifyResult.DELIVERED

    def ensure_server_up(self, *, try_restart: bool = True) -> bool:
        return True


def test_a_plain_class_satisfies_the_protocol() -> None:
    notifier: Notifier = _Fake()
    assert notifier.push("t", "b") is NotifyResult.DELIVERED
