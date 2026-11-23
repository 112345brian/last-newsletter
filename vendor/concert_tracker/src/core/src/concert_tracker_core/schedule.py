"""A daily scheduled run of `concert-tracker`: what the task is, as plain values.

Pure rules, no I/O. A `TaskSpec` is what the owner would be asked to approve (name, program,
arguments, time of day); an `InstalledTask` is what the operating system's scheduler reports back,
which may differ (someone edited it by hand). `plan_for` says what installing would do. The
scheduler itself sits behind a port in the application layer.

Nothing here carries a secret: a task is a command line, and anything the command needs from the
environment (API keys) comes from the user's own environment when it runs.
"""

from __future__ import annotations

__arbor__ = {"ring": "core"}

import re
from dataclasses import dataclass
from enum import StrEnum

TASK_NAME = "ConcertTracker Run"
DEFAULT_TIME = "06:30"
# `schtasks /TR` refuses anything longer than this.
MAX_COMMAND_CHARS = 261
HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")
_NEEDS_QUOTES = re.compile(r'[\s"]')


class ScheduleError(ValueError):
    """The schedule asked for cannot be expressed (bad time, command too long)."""


class SchedulerError(Exception):
    """The scheduler could not do what was asked; the message says why."""


class SchedulerUnavailableError(SchedulerError):
    """There is no scheduler here (not Windows, or `schtasks` is missing)."""


class SchedulerDeniedError(SchedulerError):
    """The scheduler refused: this account may not change tasks."""


@dataclass(frozen=True, slots=True, order=True)
class TimeOfDay:
    hour: int
    minute: int

    def __post_init__(self) -> None:
        if not (0 <= self.hour < HOURS_PER_DAY and 0 <= self.minute < MINUTES_PER_HOUR):
            msg = f"{self.hour}:{self.minute:02d} is not a time of day"
            raise ScheduleError(msg)

    @classmethod
    def parse(cls, text: str) -> TimeOfDay:
        """`HH:MM` on a 24-hour clock (`6:30` is fine); anything else is an error."""
        found = _TIME.match(text.strip())
        if found is None:
            msg = f"time {text!r} must look like HH:MM on a 24-hour clock, e.g. 06:30"
            raise ScheduleError(msg)
        return cls(int(found.group(1)), int(found.group(2)))

    @property
    def text(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def quote_argument(argument: str) -> str:
    """One argument as the Windows command line wants it: quoted only when it has to be."""
    if '"' in argument or "\x00" in argument:
        msg = f"argument {argument!r} contains a quote or NUL, which a task cannot carry"
        raise ScheduleError(msg)
    if argument and not _NEEDS_QUOTES.search(argument):
        return argument
    # A trailing backslash would escape the closing quote, so it is doubled.
    doubled = "\\" * (len(argument) - len(argument.rstrip("\\")))
    return f'"{argument}{doubled}"'


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """The task to register: run `program` with `arguments` every day at `at`."""

    program: str
    arguments: tuple[str, ...]
    at: TimeOfDay
    name: str = TASK_NAME

    def __post_init__(self) -> None:
        if not self.program.strip():
            msg = "the task needs a program to run"
            raise ScheduleError(msg)
        length = len(self.command_line)
        if length > MAX_COMMAND_CHARS:
            msg = (
                f"the task command is {length} characters; Task Scheduler allows "
                f"{MAX_COMMAND_CHARS}. Use a shorter --data-dir."
            )
            raise ScheduleError(msg)

    @property
    def argument_text(self) -> str:
        return " ".join(quote_argument(a) for a in self.arguments)

    @property
    def command_line(self) -> str:
        return f"{quote_argument(self.program)} {self.argument_text}".rstrip()


@dataclass(frozen=True, slots=True)
class InstalledTask:
    """A registered task as the scheduler reports it. `at` is None if it has no daily trigger."""

    name: str
    program: str
    argument_text: str
    at: TimeOfDay | None


class InstallAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"  # exists but differs; installing replaces it
    UNCHANGED = "unchanged"  # exists exactly as asked; installing does nothing


def _same_program(left: str, right: str) -> bool:
    return left.strip().strip('"').casefold() == right.strip().strip('"').casefold()


def plan_for(spec: TaskSpec, installed: InstalledTask | None) -> InstallAction:
    """What installing `spec` would do, given what is registered under its name now."""
    if installed is None:
        return InstallAction.CREATE
    same = (
        _same_program(installed.program, spec.program)
        and installed.argument_text.strip() == spec.argument_text
        and installed.at == spec.at
    )
    return InstallAction.UNCHANGED if same else InstallAction.UPDATE
