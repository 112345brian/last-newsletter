from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta

from notification_port.ntfy_policy import (
    SPOOL_MAX,
    PendingPush,
    SpoolEntry,
    bound_spool,
    build_publish_request,
    flush_spool,
    pending_push,
    should_spool,
    spool_entry,
)

def _body(req: urllib.request.Request) -> bytes:
    assert isinstance(req.data, bytes)
    return req.data


NOW = datetime(2026, 11, 6, 12, 0, 0)


def _entry(title: str, age_h: float = 1.0) -> dict[str, object]:
    return spool_entry(now=NOW - timedelta(hours=age_h), title=title, body="b", priority="high", tags="", click=None, actions=None)


def test_only_high_priorities_spool() -> None:
    assert [should_spool(p) for p in ("min", "default", "high", "urgent", "max")] == [False, False, True, True, True]


def test_bound_spool_keeps_the_newest() -> None:
    entries: list[SpoolEntry] = [{"n": i} for i in range(SPOOL_MAX + 5)]
    assert bound_spool(entries) == entries[-SPOOL_MAX:]


def test_plain_request_headers_and_auth() -> None:
    req = build_publish_request(server="https://s", topic="t", token="k", title="H\u00e9llo", body="b", priority="high",
                                tags="a,b", click="http://c", actions=None)
    assert req.full_url == "https://s/t"
    assert req.get_header("Title") == "H?llo"
    assert req.get_header("Authorization") == "Bearer k"
    assert (req.get_header("Tags"), req.get_header("Click"), req.get_header("Priority")) == ("a,b", "http://c", "high")
    assert req.data == b"b"


def test_no_token_means_no_authorization_header() -> None:
    req = build_publish_request(server="https://s", topic="t", token="", title="x", body="b", priority="default",
                                tags="", click=None, actions=None)
    assert not req.has_header("Authorization")


def test_actions_use_the_json_api_capped_at_three() -> None:
    actions = [{"action": "view", "label": str(i)} for i in range(5)]
    req = build_publish_request(server="https://s", topic="t", token="", title="T\u00e9", body="b", priority="urgent",
                                tags=" a , ,b", click="http://c", actions=actions)
    assert req.full_url == "https://s"
    payload = json.loads(_body(req))
    assert payload["topic"] == "t" and payload["title"] == "T\u00e9" and payload["priority"] == 5
    assert payload["tags"] == ["a", "b"] and payload["click"] == "http://c" and len(payload["actions"]) == 3


def test_unknown_priority_is_default_in_the_json_api() -> None:
    req = build_publish_request(server="https://s", topic="t", token="", title="x", body="b", priority="weird", tags="",
                                click=None, actions=[{"action": "view"}])
    assert json.loads(_body(req))["priority"] == 3


def test_pending_push_defaults_and_prefix() -> None:
    assert pending_push({}) == PendingPush(title="[delayed] ", body="", priority="default", tags="", click=None, actions=None)
    p = pending_push({"title": "T", "body": "B", "priority": "high", "tags": "x", "click": "u", "actions": [{"a": 1}]})
    assert p == PendingPush("[delayed] T", "B", "high", "x", "u", [{"a": 1}])


def test_flush_drops_stale_and_sends_the_rest_in_order() -> None:
    sent: list[str] = []
    kept = flush_spool([_entry("old", 30), _entry("a"), _entry("b")], now=NOW, resend=lambda p: sent.append(p.title) or True)
    assert sent == ["[delayed] a", "[delayed] b"] and kept == []


def test_flush_keeps_the_rest_when_the_server_flaps() -> None:
    entries: list[SpoolEntry] = [_entry("a"), _entry("b"), _entry("c")]
    calls = iter([True, False])
    assert flush_spool(entries, now=NOW, resend=lambda p: next(calls)) == entries[1:]


def test_unreadable_timestamp_is_stale() -> None:
    bad = {"ts": "not a date", "title": "x"}
    sent: list[PendingPush] = []
    assert flush_spool([bad], now=NOW, resend=lambda p: sent.append(p) or True) == [] and sent == []
    assert flush_spool([{"title": "x"}], now=NOW, resend=lambda p: True) == []


def test_empty_spool_flushes_to_empty() -> None:
    assert flush_spool([], now=NOW, resend=lambda p: True) == []
