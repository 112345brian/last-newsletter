from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from process_lock.file_lock import cross_process_file_lock, replace_with_retry


def test_lock_creates_missing_parent_and_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "drain.lock"
    with cross_process_file_lock(lock_path, timeout_s=1):
        assert lock_path.exists()


def test_sequential_acquisitions_do_not_deadlock(tmp_path: Path) -> None:
    lock_path = tmp_path / "drain.lock"
    with cross_process_file_lock(lock_path, timeout_s=1):
        pass
    with cross_process_file_lock(lock_path, timeout_s=1):
        pass


def test_contended_lock_raises_timeout_by_default(tmp_path: Path) -> None:
    lock_path = tmp_path / "drain.lock"
    holder_ready = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with cross_process_file_lock(lock_path, timeout_s=None):
            holder_ready.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holder_ready.wait(timeout=5)
        with pytest.raises(TimeoutError, match="drain"):
            with cross_process_file_lock(lock_path, timeout_s=0.05, label="drain"):
                pass
    finally:
        release.set()
        thread.join(timeout=5)


def test_contended_lock_proceeds_unlocked_when_asked(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    lock_path = tmp_path / "drain.lock"
    holder_ready = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with cross_process_file_lock(lock_path, timeout_s=None):
            holder_ready.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holder_ready.wait(timeout=5)
        ran = False
        with caplog.at_level(logging.WARNING):
            with cross_process_file_lock(lock_path, timeout_s=0.05, on_timeout="proceed", label="registry"):
                ran = True
        assert ran
        assert any("registry" in record.message for record in caplog.records)
    finally:
        release.set()
        thread.join(timeout=5)


def test_lock_is_released_after_the_with_block(tmp_path: Path) -> None:
    lock_path = tmp_path / "drain.lock"
    with cross_process_file_lock(lock_path, timeout_s=1):
        pass
    # A second waiter should acquire promptly now that the first released it.
    acquired = threading.Event()

    def take() -> None:
        with cross_process_file_lock(lock_path, timeout_s=1):
            acquired.set()

    thread = threading.Thread(target=take)
    thread.start()
    thread.join(timeout=5)
    assert acquired.is_set()


def test_thread_lock_is_taken_first_and_serializes_same_process_callers(tmp_path: Path) -> None:
    lock_path = tmp_path / "drain.lock"
    guard = threading.Lock()
    order: list[str] = []
    second_entered = threading.Event()

    def first() -> None:
        with cross_process_file_lock(lock_path, timeout_s=1, thread_lock=guard):
            order.append("first-start")
            time.sleep(0.1)
            order.append("first-end")

    def second() -> None:
        with cross_process_file_lock(lock_path, timeout_s=1, thread_lock=guard):
            second_entered.set()
            order.append("second")

    t1 = threading.Thread(target=first)
    t1.start()
    time.sleep(0.02)  # let `first` take the thread_lock before `second` tries
    t2 = threading.Thread(target=second)
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert second_entered.is_set()
    assert order == ["first-start", "first-end", "second"]


def test_replace_with_retry_moves_the_file(tmp_path: Path) -> None:
    src = tmp_path / "a.tmp"
    dst = tmp_path / "a.json"
    src.write_text("content")
    replace_with_retry(src, dst)
    assert not src.exists()
    assert dst.read_text() == "content"


def test_replace_with_retry_retries_transient_permission_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    src = tmp_path / "a.tmp"
    dst = tmp_path / "a.json"
    src.write_text("content")
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(a: object, b: object) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("Access is denied")
        real_replace(a, b)

    monkeypatch.setattr(os, "replace", flaky)
    replace_with_retry(src, dst)
    assert calls["n"] == 3
    assert dst.read_text() == "content"


def test_replace_with_retry_raises_after_exhausting_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    src = tmp_path / "a.tmp"
    dst = tmp_path / "a.json"
    src.write_text("content")

    def always_denied(a: object, b: object) -> None:
        raise PermissionError("Access is denied")

    monkeypatch.setattr(os, "replace", always_denied)
    with pytest.raises(PermissionError):
        replace_with_retry(src, dst)


def test_replace_with_retry_does_not_retry_other_os_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    src = tmp_path / "a.tmp"
    dst = tmp_path / "a.json"
    src.write_text("content")
    calls = {"n": 0}

    def not_found(a: object, b: object) -> None:
        calls["n"] += 1
        raise FileNotFoundError("gone")

    monkeypatch.setattr(os, "replace", not_found)
    with pytest.raises(FileNotFoundError):
        replace_with_retry(src, dst)
    assert calls["n"] == 1
