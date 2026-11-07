"""`fetch-raw` on fakes: nothing real is fetched, nothing is written outside tmp_path."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from last_newsletter_adapter_storage.raw_message_store import (
    FileRawMessageStore,
    RawStoreEmailSource,
)
from last_newsletter_cli.main import ConfigError, fetch_raw, raw_since
from last_newsletter_core.entities import EmailMessage

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)


class _Mailbox:
    def __init__(self, messages: list[EmailMessage]) -> None:
        self._messages = messages

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        return [m for m in self._messages if m.received_at >= since]


def _msg(n: int) -> EmailMessage:
    return EmailMessage(
        message_id=f"<{n}@x>",
        sender="a@x.test",
        subject=f"s{n}",
        received_at=datetime(2026, 11, n, tzinfo=UTC),
        body_text=f"body {n}",
    )


def test_fetch_raw_counts_and_is_idempotent(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    box = _Mailbox([_msg(1), _msg(2), _msg(3)])
    first = fetch_raw(box, store, since=datetime(2026, 11, 2, tzinfo=UTC))
    assert (first.fetched, first.new, first.already_stored) == (2, 2, 0)
    second = fetch_raw(box, store, since=datetime(2026, 11, 1, tzinfo=UTC))
    assert (second.fetched, second.new, second.already_stored) == (3, 1, 2)
    assert len(list(store.list())) == 3


def test_fetch_raw_empty_mailbox(tmp_path: Path) -> None:
    result = fetch_raw(_Mailbox([]), FileRawMessageStore(tmp_path), since=_NOW)
    assert (result.fetched, result.new) == (0, 0)


def test_raw_since_variants() -> None:
    assert raw_since(since=None, days=None, now=_NOW) == datetime(2026, 10, 31, 12, tzinfo=UTC)
    assert raw_since(since=None, days=2, now=_NOW) == datetime(2026, 11, 5, 12, tzinfo=UTC)
    assert raw_since(since="2026-11-01", days=None, now=_NOW) == datetime(2026, 11, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("since", "days"), [("2026-11-01", 3), ("yesterday", None), (None, 0), (None, -1)]
)
def test_raw_since_rejects_bad_input(since: str | None, days: int | None) -> None:
    with pytest.raises(ConfigError):
        raw_since(since=since, days=days, now=_NOW)


def test_raw_since_resumes_from_watermark_with_a_day_of_overlap() -> None:
    mark = datetime(2026, 11, 6, 8, tzinfo=UTC)
    assert raw_since(since=None, days=None, now=_NOW, watermark=mark) == datetime(
        2026, 11, 5, 8, tzinfo=UTC
    )
    # Explicit window beats the watermark.
    assert raw_since(since=None, days=2, now=_NOW, watermark=mark) == datetime(
        2026, 11, 5, 12, tzinfo=UTC
    )


def test_watermark_roundtrip_and_bad_file(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path / "raw")
    assert store.read_watermark() is None
    mark = datetime(2026, 11, 6, 8, tzinfo=UTC)
    store.write_watermark(mark)
    assert store.read_watermark() == mark
    (tmp_path / "raw" / ".watermark").write_text("garbage", encoding="utf-8")
    assert store.read_watermark() is None
    assert list(store.list()) == []  # the watermark is not a message


def test_raw_store_email_source_filters_by_received_at(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    for n in (1, 2, 3):
        store.put(_msg(n))
    got = RawStoreEmailSource(store).fetch_since(datetime(2026, 11, 2, tzinfo=UTC))
    assert sorted(m.message_id for m in got) == ["<2@x>", "<3@x>"]
