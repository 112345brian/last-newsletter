"""File-backed raw message store: one JSON file per source email, keyed by a stable id.

Shaped as the event-ledger design's `RawMessageStore` port (`put(message) -> RawRef`,
`get(ref)`, plus `list` for iteration). Until core's port lands on main, `RawMessageStore`
below is a local Protocol with that exact shape; switch the import then.

Guarantees:
- Idempotent: the id is a hash of the Message-ID (or, when missing, of the message's
  content), so re-putting the same message is a no-op and never rewrites the file.
- Atomic: written to a temp file in the same directory, then renamed into place; a crash
  leaves either no file or a whole one.
- Private: files are 0600 and the directory 0700 -- this is real mail.
- Safe under concurrent writers: puts take a cross-process lock on `<root>/.lock`.
- A corrupt file is moved to `<root>/quarantine/` and treated as absent, never fatal.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from process_lock.file_lock import cross_process_file_lock, replace_with_retry

from last_newsletter_core.entities import EmailMessage

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOCK_TIMEOUT_S = 30.0
_SCHEMA_VERSION = 1
_WATERMARK = ".watermark"
_ID_LENGTH = 64  # hex sha256


@dataclass(frozen=True, slots=True)
class RawRef:
    """Opaque stable handle to a stored message (hex sha256, safe as a file name)."""

    id: str


class RawMessageStore(Protocol):
    def put(self, message: EmailMessage) -> RawRef: ...
    def get(self, ref: RawRef) -> EmailMessage | None: ...
    def list(self) -> Iterator[RawRef]: ...


def raw_ref_for(message: EmailMessage) -> RawRef:
    """Stable id: hash of the Message-ID; without one, of the message's identifying content."""
    key = message.message_id.strip()
    if not key:
        stamp = message.received_at.isoformat()
        key = f"{message.sender}\x00{message.subject}\x00{stamp}\x00{message.body_text}"
    return RawRef(hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest())


def _to_dict(message: EmailMessage) -> dict[str, Any]:
    return {
        "schema": _SCHEMA_VERSION,
        "message_id": message.message_id,
        "sender": message.sender,
        "subject": message.subject,
        "received_at": message.received_at.isoformat(),
        "body_text": message.body_text,
        "source_label": message.source_label,
    }


def _from_dict(data: dict[str, Any]) -> EmailMessage:
    if data["schema"] != _SCHEMA_VERSION:
        msg = f"unknown schema {data['schema']!r}"
        raise ValueError(msg)
    return EmailMessage(
        message_id=data["message_id"],
        sender=data["sender"],
        subject=data["subject"],
        received_at=datetime.fromisoformat(data["received_at"]),
        body_text=data["body_text"],
        source_label=data["source_label"],
    )


class FileRawMessageStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._quarantine = self._root / "quarantine"

    def put(self, message: EmailMessage) -> RawRef:
        ref = raw_ref_for(message)
        self._ensure_dirs()
        with cross_process_file_lock(
            self._root / ".lock", timeout_s=_LOCK_TIMEOUT_S, label="raw message store"
        ):
            path = self._path(ref)
            if path.exists() and self._read(path) is not None:
                return ref
            self._write_atomic(path, message)
        return ref

    def get(self, ref: RawRef) -> EmailMessage | None:
        self._check_id(ref.id)
        return self._read(self._path(ref))

    def list(self) -> Iterator[RawRef]:
        if not self._root.is_dir():
            return
        for path in sorted(self._root.glob("*.json")):
            ref = RawRef(path.stem)
            if self._read(path) is not None:
                yield ref

    def read_watermark(self) -> datetime | None:
        """When the last successful fetch started (None if never, or the file is unreadable --
        a bad watermark only costs a wider re-fetch, which is idempotent)."""
        try:
            value = datetime.fromisoformat((self._root / _WATERMARK).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if value.tzinfo is not None else None

    def write_watermark(self, when: datetime) -> None:
        self._ensure_dirs()
        with cross_process_file_lock(
            self._root / ".lock", timeout_s=_LOCK_TIMEOUT_S, label="raw message store"
        ):
            self._write_text_atomic(self._root / _WATERMARK, when.isoformat())

    def _path(self, ref: RawRef) -> Path:
        self._check_id(ref.id)
        return self._root / f"{ref.id}.json"

    @staticmethod
    def _check_id(raw_id: str) -> None:
        if len(raw_id) != _ID_LENGTH or any(c not in "0123456789abcdef" for c in raw_id):
            msg = f"not a raw message id: {raw_id!r}"
            raise ValueError(msg)

    def _ensure_dirs(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _read(self, path: Path) -> EmailMessage | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError):
            self._quarantine_file(path)
            return None
        try:
            return _from_dict(json.loads(raw))
        except (ValueError, KeyError, TypeError):
            self._quarantine_file(path)
            return None

    def _quarantine_file(self, path: Path) -> None:
        with contextlib.suppress(OSError):
            self._quarantine.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = self._quarantine / f"{path.name}.{os.getpid()}.{os.urandom(4).hex()}"
            replace_with_retry(path, target)

    def _write_atomic(self, path: Path, message: EmailMessage) -> None:
        self._write_text_atomic(path, json.dumps(_to_dict(message), ensure_ascii=True, indent=1))

    def _write_text_atomic(self, path: Path, payload: str) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=self._root, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            replace_with_retry(tmp_name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                Path(tmp_name).unlink()
            raise


class RawStoreEmailSource:
    """An `EmailSource` that reads only from the raw store: no network, no credentials."""

    def __init__(self, store: RawMessageStore) -> None:
        self._store = store

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        messages = (self._store.get(ref) for ref in self._store.list())
        return [m for m in messages if m is not None and m.received_at >= since]
