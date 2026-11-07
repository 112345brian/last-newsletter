from __future__ import annotations

import dataclasses
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from durable_outbox.errors import OutboxWriteError
from durable_outbox.outbox import HostedOutbox, OutboxEntry


def _dead_pid() -> int:
    """A pid guaranteed not to be alive right now: a subprocess we spawned and waited on."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# -- enqueue / entries -------------------------------------------------------


def test_enqueue_round_trips_through_entries(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"a": 1})
    (loaded,) = outbox.entries()
    assert loaded.id == entry.id
    assert loaded.kind == "event"
    assert loaded.payload == {"a": 1}
    assert loaded.attempts == 0


def test_entries_are_returned_in_enqueue_order(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    first = outbox.enqueue("event", {"n": 1})
    second = outbox.enqueue("event", {"n": 2})
    third = outbox.enqueue("event", {"n": 3})
    assert [e.id for e in outbox.entries()] == [first.id, second.id, third.id]


def test_enqueue_never_overwrites_an_existing_entry(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    outbox.enqueue("event", {"n": 1})
    outbox.enqueue("event", {"n": 2})
    assert len(outbox.entries()) == 2


def test_has_entries_reflects_directory_contents(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path / "missing")
    assert outbox.has_entries() is False
    outbox.enqueue("event", {"n": 1})
    assert outbox.has_entries() is True


def test_entry_payload_with_a_non_json_native_value_round_trips_as_its_str_form(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)

    class Weird:
        def __str__(self) -> str:
            return "weird-value"

    outbox.enqueue("event", {"when": Weird()})
    (loaded,) = outbox.entries()
    assert loaded.payload == {"when": "weird-value"}


# -- record_attempt / release_lease / remove --------------------------------


def test_record_attempt_increments_and_preserves_identity(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"n": 1})
    updated = outbox.record_attempt(entry, error="boom")
    assert updated.id == entry.id
    assert updated.attempts == 1
    assert updated.last_error == "boom"
    (loaded,) = outbox.entries()
    assert loaded.attempts == 1
    assert loaded.last_error == "boom"


def test_record_attempt_can_shrink_the_payload_on_partial_success(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"items": [1, 2, 3]})
    updated = outbox.record_attempt(entry, error="partial", payload={"items": [3]})
    assert updated.payload == {"items": [3]}
    (loaded,) = outbox.entries()
    assert loaded.payload == {"items": [3]}


def test_record_attempt_truncates_a_very_long_error(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"n": 1})
    updated = outbox.record_attempt(entry, error="x" * 1000)
    assert len(updated.last_error) == 500


def test_record_attempt_can_park_an_entry(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"n": 1})
    updated = outbox.record_attempt(entry, error="give up", parked=True)
    assert updated.parked is True
    (loaded,) = outbox.entries()
    assert loaded.parked is True


def test_release_lease_clears_the_lease_without_counting_an_attempt(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"n": 1}, lease_s=60)
    assert entry.leased() is True
    released = outbox.release_lease(entry, error="ctrl-c")
    assert released.attempts == entry.attempts
    assert released.lease_until is None
    assert released.leased() is False
    (loaded,) = outbox.entries()
    assert loaded.leased() is False
    assert loaded.last_error == "ctrl-c"


def test_remove_deletes_the_entry_file(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"n": 1})
    assert len(outbox.entries()) == 1
    outbox.remove(entry)
    assert outbox.entries() == []


def test_remove_on_an_already_missing_entry_does_not_raise(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"n": 1})
    outbox.remove(entry)
    outbox.remove(entry)  # idempotent


# -- leasing ------------------------------------------------------------------


def test_entry_is_leased_only_while_within_the_window_and_the_holder_is_alive() -> None:
    now = time.time()
    live = dataclasses.replace(
        OutboxEntry(id="1", seq=1, kind="event", created_at="now", attempts=0, payload=None),
        lease_until=now + 60, lease_pid=__import__("os").getpid(),
        lease_started=__import__("psutil").Process().create_time(),
    )
    assert live.leased() is True


def test_entry_is_not_leased_once_lease_until_has_passed() -> None:
    now = time.time()
    expired = dataclasses.replace(
        OutboxEntry(id="1", seq=1, kind="event", created_at="now", attempts=0, payload=None),
        lease_until=now - 1, lease_pid=__import__("os").getpid(),
        lease_started=__import__("psutil").Process().create_time(),
    )
    assert expired.leased() is False


def test_entry_is_not_leased_when_the_holder_pid_is_dead() -> None:
    dead_pid = _dead_pid()
    now = time.time()
    entry = dataclasses.replace(
        OutboxEntry(id="1", seq=1, kind="event", created_at="now", attempts=0, payload=None),
        lease_until=now + 60, lease_pid=dead_pid, lease_started=0.0,
    )
    assert entry.leased() is False


def test_entry_with_no_lease_is_never_leased() -> None:
    entry = OutboxEntry(id="1", seq=1, kind="event", created_at="now", attempts=0, payload=None)
    assert entry.leased() is False


# -- status -------------------------------------------------------------------


def test_status_is_empty_for_a_fresh_outbox(tmp_path: Path) -> None:
    status = HostedOutbox(tmp_path / "missing").status()
    assert status.empty is True
    assert status.pending == 0


def test_status_counts_pending_parked_and_excludes_markers(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    outbox.enqueue("event", {"n": 1})
    parked_entry = outbox.enqueue("event", {"n": 2})
    outbox.record_attempt(parked_entry, error="give up", parked=True)
    outbox.enqueue("applied_marker", {"n": 3})
    status = outbox.status()
    assert status.pending == 1
    assert status.parked == 1
    assert status.empty is False


def test_status_excludes_currently_leased_entries_from_pending(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    outbox.enqueue("event", {"n": 1}, lease_s=60)
    status = outbox.status()
    assert status.pending == 0
    assert status.empty is True


def test_status_reports_the_oldest_entry(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    first = outbox.enqueue("event", {"n": 1})
    outbox.enqueue("event", {"n": 2})
    status = outbox.status()
    assert status.oldest_created_at == first.created_at
    assert status.oldest_age_minutes is not None
    assert status.oldest_age_minutes >= 0


# -- corrupt / quarantine -------------------------------------------------------


def test_a_corrupt_entry_file_is_quarantined_not_raised(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    bad = tmp_path / f"{'0' * 20}-{'a' * 32}.json"
    bad.write_text("not json", encoding="utf-8")
    assert outbox.entries() == []
    assert outbox.quarantined_count() == 1
    assert not bad.exists()


def test_an_entry_missing_a_required_field_is_quarantined(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    bad = tmp_path / f"{'0' * 20}-{'b' * 32}.json"
    bad.write_text('{"schema": 1, "id": "x"}', encoding="utf-8")
    assert outbox.entries() == []
    assert outbox.quarantined_count() == 1


def test_an_entry_with_an_unknown_schema_version_is_quarantined(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    entry = outbox.enqueue("event", {"n": 1})
    path = tmp_path / f"{entry.id}.json"
    doc = path.read_text(encoding="utf-8").replace('"schema": 1', '"schema": 99')
    path.write_text(doc, encoding="utf-8")
    assert outbox.entries() == []
    assert outbox.quarantined_count() == 1


def test_a_file_not_matching_the_entry_name_pattern_is_ignored(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "drain.lock").write_text("", encoding="utf-8")
    (tmp_path / "notanentry.json").write_text("{}", encoding="utf-8")
    assert outbox.entries() == []
    assert outbox.quarantined_count() == 0


def test_status_counts_quarantined_files(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{'0' * 20}-{'c' * 32}.json").write_text("not json", encoding="utf-8")
    outbox.entries()  # triggers quarantine
    status = outbox.status()
    assert status.quarantined == 1
    assert status.empty is False


# -- write failures -------------------------------------------------------------


def test_write_atomic_raises_outbox_write_error_on_a_non_retryable_os_error(tmp_path: Path) -> None:
    # Point the outbox at a path that is a regular file, not a directory: mkdir() fails
    # immediately with FileExistsError (not PermissionError), so _write_atomic must not
    # spend its ~32s retry budget before surfacing the failure.
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    outbox = HostedOutbox(blocker)
    with pytest.raises(OutboxWriteError):
        outbox.enqueue("event", {"n": 1})


# -- drain lock -----------------------------------------------------------------


def test_drain_lock_is_exclusive(tmp_path: Path) -> None:
    outbox = HostedOutbox(tmp_path)
    holder_ready = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with outbox.drain_lock(timeout_s=None):
            holder_ready.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holder_ready.wait(timeout=5)
        with pytest.raises(TimeoutError):
            with outbox.drain_lock(timeout_s=0.05):
                pass
    finally:
        release.set()
        thread.join(timeout=5)
