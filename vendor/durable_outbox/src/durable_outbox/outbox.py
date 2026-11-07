"""Durable local outbox for hosted (Supabase) UPLOADS: the file store.

A hosted upload is a write whose data originates locally (a scrape's rows, a
scoring pass's cache patch, a rotation cursor). If the hosted write fails, that
data must not be lost and must not be the reason a pipeline stage fails: it is
recorded here and replayed later by ``state.hosted_upload.drain_outbox``. This
module is only the store; it never talks to the network and never decides what a
failure means (that is ``state.hosted_upload``).

Write-ahead: an upload persists its entry here BEFORE the first send, holding a *lease* (``lease_until``
plus the sender's pid and process start time) while the request is in flight, and removes it only after
Supabase confirms. A killed sender (``taskkill /F``, logoff, power loss, OOM) therefore leaves the entry on
disk; the drain treats it as replayable as soon as the lease is dead (the pid is gone, or ``lease_until``
passed) and skips it while a live process still holds it.

Layout: one directory, ``<RUNTIME_DIR>/hosted_outbox/``, one JSON file per
entry, named ``<seq:020d>-<uuid>.json`` (``seq`` is ``time.time_ns()`` at
enqueue, so a lexical sort is queue order). Entries are IMMUTABLE once written
-- enqueue only ever creates a new file -- with one exception: the single
drainer (guarded by ``drain.lock``) rewrites an entry's bookkeeping fields
(``attempts``, ``last_error`` ...) after a failed replay, and deletes an entry
after a confirmed success. Because writers never touch an existing file,
concurrent scheduled tasks (the nightly stages, the hourly drain) need no lock
to enqueue, and a half-written file is impossible to observe: every write is a
unique tmp file, fsynced, then ``replace_with_retry`` (the Windows
``PermissionError`` retry the rest of ``src/state/`` uses).

Entry kinds are defined in ``state.hosted_upload``; this store treats the
``payload`` as opaque JSON. An ``applied_marker`` entry is the supersession
record (see that module): "these keys were written directly, newer than any
earlier queued entry for them".

Corrupt or unreadable entry files are never silently discarded and never
re-crash a drain: they are moved to ``quarantine/`` (kept for inspection or a
manual replay), logged at ERROR, and counted in :class:`OutboxStatus`.

Everything is UTF-8 (``encoding="utf-8"``), per the repo's Windows convention.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from process_lock.file_lock import cross_process_file_lock, replace_with_retry
from durable_outbox.errors import OutboxWriteError

# ~32s of total patience. 2026-10-08 the nightly's outbox directory refused writes (and even listing) for
# longer than the earlier ~4s budget, so a Supabase statement timeout then had nowhere to park its data.
_WRITE_ATTEMPTS = 12
_WRITE_BACKOFF_S = 0.5
_WRITE_BACKOFF_CAP_S = 5.0

# Removing a sent entry races the readers of the same directory (the tracker's pending-activity read, a
# second drain's listing): Python opens files without FILE_SHARE_DELETE, so an unlink while a reader holds
# the file fails with WinError 32/5 for the few milliseconds of its read. ~1.5s of patience is plenty.
_REMOVE_ATTEMPTS = 8
_REMOVE_BACKOFF_S = 0.02

logger = logging.getLogger("jobsearch.hosted_outbox")

SCHEMA_VERSION = 1
_ENTRY_RE = re.compile(r"^(\d{20})-([0-9a-f]{32})\.json$")
_REQUIRED_FIELDS = ("schema", "id", "seq", "kind", "created_at", "attempts", "payload")


# How long a sender may hold an entry mid-request before the drain may replay it anyway. The pid check
# below is the fast path (a killed sender is recognised at once); this bounds a wedged-but-alive one and a
# reused pid. Generous: a large batch with per-chunk retries can run for many minutes. Replay is idempotent,
# so the worst case of a too-short lease is a harmless duplicate send, never loss.
LEASE_SECONDS = 30 * 60


def _process_alive(pid: int | None, started: float | None) -> bool:
    if pid is None:
        return False
    try:
        if not psutil.pid_exists(pid):
            return False
        if started is not None and abs(psutil.Process(pid).create_time() - started) > 1.0:
            return False  # the pid now belongs to a different process
        return True
    except psutil.Error:
        return False


def _own_lease() -> tuple[int, float | None]:
    pid = os.getpid()
    try:
        return pid, psutil.Process(pid).create_time()
    except psutil.Error:
        return pid, None


_SEQ_LOCK = threading.Lock()
_last_seq = 0


def _next_seq() -> int:
    """``time.time_ns()``, forced strictly increasing within this process. The Windows clock ticks in
    milliseconds or worse, so two enqueues in a row can read the same value; ordering them by a random uuid
    would replay a newer write before an older one. (Concurrent writers in DIFFERENT processes can still tie;
    they are independent writes by definition, so either order is the order they happened in.)"""
    global _last_seq
    with _SEQ_LOCK:
        _last_seq = max(time.time_ns(), _last_seq + 1)
        return _last_seq


@dataclass(frozen=True)
class OutboxEntry:
    id: str
    seq: int
    kind: str
    created_at: str
    attempts: int
    payload: Any
    where: str = ""
    last_error: str = ""
    last_attempt_at: str | None = None
    parked: bool = False
    lease_until: float | None = None   # epoch seconds; set while a live sender is mid-request
    lease_pid: int | None = None
    lease_started: float | None = None  # that process's start time, so a reused pid is not mistaken for it
    path: Path | None = field(default=None, compare=False)

    def leased(self, now: float | None = None) -> bool:
        """True while a live process still holds this entry's lease (the drain must not replay it)."""
        if self.lease_until is None:
            return False
        if self.lease_until <= (time.time() if now is None else now):
            return False  # staleness timeout: a wedged or vanished holder
        return _process_alive(self.lease_pid, self.lease_started)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION, "id": self.id, "seq": self.seq, "kind": self.kind,
            "created_at": self.created_at, "attempts": self.attempts, "where": self.where,
            "last_error": self.last_error, "last_attempt_at": self.last_attempt_at,
            "parked": self.parked, "lease_until": self.lease_until, "lease_pid": self.lease_pid,
            "lease_started": self.lease_started, "payload": self.payload,
        }


@dataclass(frozen=True)
class OutboxStatus:
    """What is waiting, for the health warning and ``outbox status``."""

    pending: int = 0           # replayable entries (markers excluded)
    parked: int = 0            # entries the drain skips until told otherwise
    quarantined: int = 0       # unreadable files moved aside
    oldest_age_minutes: float | None = None
    oldest_created_at: str | None = None

    @property
    def empty(self) -> bool:
        return self.pending == 0 and self.parked == 0 and self.quarantined == 0

    def describe(self) -> str:
        parts: list[str] = []
        if self.pending:
            parts.append(f"{self.pending} hosted write(s) queued, oldest {self.oldest_age_minutes or 0:.0f} min")
        if self.parked:
            parts.append(f"{self.parked} PARKED (will not retry on their own; "
                         "`job-search admin outbox drain --retry-parked`)")
        if self.quarantined:
            parts.append(f"{self.quarantined} unreadable file(s) in the outbox quarantine directory")
        return "; ".join(parts)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _minutes_since(iso: str) -> float:
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(UTC) - then).total_seconds() / 60.0)


class HostedOutbox:
    """The directory of entries. Construct with an explicit ``directory`` in tests."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.quarantine_dir = self.directory / "quarantine"
        self._drain_lock_path = self.directory / "drain.lock"

    # -- writing ---------------------------------------------------------

    def _write_atomic(self, path: Path, document: dict[str, Any]) -> None:
        """Unique tmp file, fsync, then replace. Raises OutboxWriteError on any OSError."""
        try:
            # default=str: never lose an entry to an exotic value (a datetime) that the live
            # request path would have rejected anyway; the replay sends its JSON form.
            text = json.dumps(document, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            raise OutboxWriteError(f"could not write hosted outbox entry {path}: {exc}") from exc
        # Creating the tmp file can itself raise PermissionError on Windows (a scanner or indexer holding the
        # directory; 2026-10-07 a scrape stage died because the outbox could not take a write after a 500).
        # replace_with_retry only covers the final rename, so retry the whole write under a fresh tmp name.
        for attempt in range(_WRITE_ATTEMPTS):
            tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                replace_with_retry(tmp, path)
                return
            except OSError as exc:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                if isinstance(exc, PermissionError) and attempt < _WRITE_ATTEMPTS - 1:
                    time.sleep(min(_WRITE_BACKOFF_S * (attempt + 1), _WRITE_BACKOFF_CAP_S))
                    continue
                raise OutboxWriteError(f"could not write hosted outbox entry {path}: {exc}") from exc

    def enqueue(
        self, kind: str, payload: Any, *, where: str = "", last_error: str = "", parked: bool = False,
        attempts: int = 0, lease_s: float | None = None,
    ) -> OutboxEntry:
        """Durably record one pending write. Never modifies an existing file. ``lease_s`` marks it as being
        sent right now by this process (write-ahead), for that many seconds."""
        pid, started = _own_lease()
        seq = _next_seq()
        entry_id = f"{seq:020d}-{uuid.uuid4().hex}"
        entry = OutboxEntry(
            id=entry_id, seq=seq, kind=kind, created_at=_now_iso(), attempts=attempts, payload=payload,
            where=where, last_error=last_error[:500], parked=parked,
            last_attempt_at=_now_iso() if attempts or last_error else None,
            lease_until=time.time() + lease_s if lease_s else None,
            lease_pid=pid if lease_s else None, lease_started=started if lease_s else None,
        )
        path = self.directory / f"{entry_id}.json"
        self._write_atomic(path, entry.to_json())
        return OutboxEntry(**{**entry.__dict__, "path": path})

    def record_attempt(
        self, entry: OutboxEntry, *, error: str, parked: bool | None = None, payload: Any = None,
    ) -> OutboxEntry:
        """Drainer only: bump ``attempts`` and keep the entry (a failed replay never loses data).
        ``payload``, when given, replaces the stored payload (a partial success shrinks it to what is left)."""
        updated = OutboxEntry(
            id=entry.id, seq=entry.seq, kind=entry.kind, created_at=entry.created_at,
            attempts=entry.attempts + 1, payload=entry.payload if payload is None else payload, where=entry.where,
            last_error=error[:500], last_attempt_at=_now_iso(),
            parked=entry.parked if parked is None else parked, path=entry.path,
        )
        path = entry.path or (self.directory / f"{entry.id}.json")
        self._write_atomic(path, updated.to_json())
        return updated

    def release_lease(self, entry: OutboxEntry, *, error: str) -> OutboxEntry:
        """The sender was interrupted (Ctrl-C) mid-request: hand the entry back to the drain at once, without
        counting an attempt that never completed."""
        updated = OutboxEntry(
            id=entry.id, seq=entry.seq, kind=entry.kind, created_at=entry.created_at, attempts=entry.attempts,
            payload=entry.payload, where=entry.where, last_error=error[:500], last_attempt_at=_now_iso(),
            parked=entry.parked, path=entry.path,
        )
        self._write_atomic(entry.path or (self.directory / f"{entry.id}.json"), updated.to_json())
        return updated

    def remove(self, entry: OutboxEntry) -> None:
        """Delete an entry. Call only after a CONFIRMED success (or a recorded supersession)."""
        path = entry.path or (self.directory / f"{entry.id}.json")
        for attempt in range(_REMOVE_ATTEMPTS):
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError as exc:
                # A reader holds the file open for milliseconds (Windows sharing violation): retry promptly.
                if attempt < _REMOVE_ATTEMPTS - 1:
                    time.sleep(_REMOVE_BACKOFF_S * (attempt + 1))
                    continue
                self._log_remove_failure(path, exc)
            except OSError as exc:
                self._log_remove_failure(path, exc)
                return

    @staticmethod
    def _log_remove_failure(path: Path, exc: OSError) -> None:
        # Leaving it means a harmless idempotent re-send next drain; say so rather than raise.
        logger.error("hosted outbox: could not remove applied entry %s (%s); it will be re-sent", path.name, exc)

    # -- reading ---------------------------------------------------------

    def _entry_paths(self) -> list[Path]:
        try:
            names = sorted(name for name in os.listdir(self.directory) if _ENTRY_RE.match(name))
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise OutboxWriteError(f"could not list hosted outbox {self.directory}: {exc}") from exc
        return [self.directory / name for name in names]

    def has_entries(self) -> bool:
        """Cheap: any entry file at all (used to skip writing a supersession marker when nothing is queued)."""
        try:
            return any(_ENTRY_RE.match(name) for name in os.listdir(self.directory))
        except OSError:
            return False

    def _quarantine(self, path: Path, reason: str) -> None:
        try:
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
            target = self.quarantine_dir / f"{path.name}.{uuid.uuid4().hex[:8]}.corrupt"
            replace_with_retry(path, target)
            where = f"moved to {target}"
        except OSError as exc:
            where = f"could NOT be moved aside ({exc}); left in place"
        message = f"hosted outbox: unreadable entry {path.name} ({reason}) {where}. The data is kept, not discarded."
        logger.error(message)
        print(f"[hosted-outbox] QUARANTINED {message}", flush=True)

    def _load(self, path: Path) -> OutboxEntry | None:
        try:
            raw = path.read_bytes().decode("utf-8")
            doc = json.loads(raw)
            if not isinstance(doc, dict) or any(key not in doc for key in _REQUIRED_FIELDS):
                raise ValueError("missing required fields")
            if doc["schema"] != SCHEMA_VERSION:
                raise ValueError(f"unknown schema version {doc['schema']!r}")
            return OutboxEntry(
                id=str(doc["id"]), seq=int(doc["seq"]), kind=str(doc["kind"]), created_at=str(doc["created_at"]),
                attempts=int(doc["attempts"]), payload=doc["payload"], where=str(doc.get("where") or ""),
                last_error=str(doc.get("last_error") or ""), last_attempt_at=doc.get("last_attempt_at"),
                parked=bool(doc.get("parked")), lease_until=doc.get("lease_until"),
                lease_pid=doc.get("lease_pid"), lease_started=doc.get("lease_started"), path=path,
            )
        except FileNotFoundError:
            return None  # removed by the drainer between listing and reading
        except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, PermissionError):
                return None  # a transient Windows sharing violation, not corruption
            self._quarantine(path, f"{type(exc).__name__}: {exc}")
            return None

    def entries(self) -> list[OutboxEntry]:
        """All readable entries in queue order. Unreadable ones are quarantined as a side effect."""
        loaded = (self._load(path) for path in self._entry_paths())
        return sorted((e for e in loaded if e is not None), key=lambda e: (e.seq, e.id))

    def quarantined_count(self) -> int:
        try:
            return sum(1 for name in os.listdir(self.quarantine_dir) if name.endswith(".corrupt"))
        except OSError:
            return 0

    def status(self, *, marker_kind: str = "applied_marker") -> OutboxStatus:
        items = [e for e in self.entries() if e.kind != marker_kind and not e.leased()]
        parked = sum(1 for e in items if e.parked)
        live = [e for e in items if not e.parked]
        oldest = min(items, key=lambda e: e.seq) if items else None
        return OutboxStatus(
            pending=len(live), parked=parked, quarantined=self.quarantined_count(),
            oldest_age_minutes=_minutes_since(oldest.created_at) if oldest else None,
            oldest_created_at=oldest.created_at if oldest else None,
        )

    # -- draining --------------------------------------------------------

    def drain_lock(self, *, timeout_s: float = 0.0):
        """Exclusive across processes (and threads: the OS lock is per open handle);
        raises TimeoutError when another drain is running."""
        return cross_process_file_lock(
            self._drain_lock_path, timeout_s=timeout_s, on_timeout="raise", label="hosted outbox drain",
        )
