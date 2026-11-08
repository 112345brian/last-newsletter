from __future__ import annotations

import multiprocessing
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from last_newsletter_adapter_storage import FileRawMessageStore
from last_newsletter_adapter_storage.raw_message_store import raw_ref_for
from last_newsletter_core.events import RawRef
from ranked_digest.entities import EmailMessage


def _msg(message_id: str = "<a@x>", body: str = "hello", subject: str = "s") -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        sender="Alice <a@x.test>",
        subject=subject,
        received_at=datetime(2026, 11, 2, 9, 30, tzinfo=UTC),
        body_text=body,
        source_label="a@x.test",
    )


def test_put_get_roundtrip(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path / "raw")
    ref = store.put(_msg())
    assert store.get(ref) == _msg()


def test_re_put_is_a_noop_and_does_not_rewrite(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    ref = store.put(_msg())
    path = tmp_path / f"{ref.removeprefix('raw:')}.json"
    before = path.stat().st_mtime_ns
    assert store.put(_msg(body="different body, same id")) == ref
    assert path.stat().st_mtime_ns == before
    assert store.get(ref) == _msg()
    assert list(store.list()) == [ref]


def test_files_are_private_and_no_temp_files_left(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path / "raw")
    ref = store.put(_msg())
    path = tmp_path / "raw" / f"{ref.removeprefix('raw:')}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not list(path.parent.glob(".tmp-*"))


def test_corrupt_file_is_quarantined_not_fatal(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    good = store.put(_msg("<good@x>"))
    bad = store.put(_msg("<bad@x>"))
    (tmp_path / f"{bad.removeprefix('raw:')}.json").write_text("{not json", encoding="utf-8")
    assert list(store.list()) == [good]
    assert store.get(bad) is None
    assert len(list((tmp_path / "quarantine").iterdir())) == 1
    # A later put heals it.
    assert store.put(_msg("<bad@x>")) == bad
    assert store.get(bad) == _msg("<bad@x>")


@pytest.mark.parametrize("payload", ['{"schema": 99}', "[]", '{"schema": 1}', "\x00\x00"])
def test_wrong_shape_files_are_quarantined(tmp_path: Path, payload: str) -> None:
    store = FileRawMessageStore(tmp_path)
    ref = store.put(_msg())
    (tmp_path / f"{ref.removeprefix('raw:')}.json").write_text(payload, encoding="utf-8")
    assert store.get(ref) is None
    assert list(store.list()) == []


def test_binary_garbage_is_quarantined(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    ref = store.put(_msg())
    (tmp_path / f"{ref.removeprefix('raw:')}.json").write_bytes(b"\xff\xfe\x00bad")
    assert store.get(ref) is None


def test_nul_and_very_long_bodies_roundtrip(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    nul = store.put(_msg("<nul@x>", body="a\x00b\x00"))
    big = store.put(_msg("<big@x>", body="é" * 5_000_000))
    assert store.get(nul) == _msg("<nul@x>", body="a\x00b\x00")
    assert store.get(big) == _msg("<big@x>", body="é" * 5_000_000)


def test_empty_store_and_missing_dir(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path / "does-not-exist")
    assert list(store.list()) == []
    assert store.get(RawRef("raw:" + "0" * 64)) is None
    assert not (tmp_path / "does-not-exist").exists()  # reading never creates it


def test_message_without_message_id_gets_content_derived_id(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    a = store.put(_msg("", body="one"))
    b = store.put(_msg("", body="two"))
    assert a != b
    assert store.put(_msg("", body="one")) == a
    assert raw_ref_for(_msg("  ")) == raw_ref_for(_msg(""))


def test_path_traversal_ids_are_rejected(tmp_path: Path) -> None:
    store = FileRawMessageStore(tmp_path)
    with pytest.raises(ValueError, match="not a raw message id"):
        store.get(RawRef("raw:../../etc/passwd"))


def _put_many(root: str, start: int) -> None:
    store = FileRawMessageStore(Path(root))
    for i in range(start, start + 20):
        store.put(_msg(f"<m{i % 30}@x>", body=f"body {i % 30}"))


def test_concurrent_writers_overlapping_messages(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_put_many, args=(str(tmp_path), n * 10)) for n in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0
    store = FileRawMessageStore(tmp_path)
    refs = list(store.list())
    assert len(refs) == 30
    assert not (tmp_path / "quarantine").exists()
    assert not list(tmp_path.glob(".tmp-*"))
