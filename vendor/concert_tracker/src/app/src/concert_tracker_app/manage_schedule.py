"""Install, inspect and remove the daily scheduled run.

The operating system's scheduler is a port. `install` is idempotent: it registers the task if it is
missing, replaces it if it differs and leaves it alone if it already matches. `remove` of a task
that is not there is a quiet no-op, so both can be run again safely.
"""

from __future__ import annotations

__arbor__ = {"ring": "app"}

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from concert_tracker_core.schedule import InstallAction, plan_for

if TYPE_CHECKING:
    from concert_tracker_core.schedule import InstalledTask, TaskSpec


class TaskScheduler(Protocol):
    def find(self, name: str) -> InstalledTask | None:
        """The task registered as `name`, or None. Read-only."""
        ...

    def register(self, spec: TaskSpec) -> None:
        """Create the task, replacing one of the same name."""
        ...

    def unregister(self, name: str) -> None: ...


@dataclass(frozen=True, slots=True)
class InstallPlan:
    spec: TaskSpec
    action: InstallAction
    installed: InstalledTask | None


class ManageSchedule:
    def __init__(self, scheduler: TaskScheduler) -> None:
        self._scheduler = scheduler

    def plan(self, spec: TaskSpec) -> InstallPlan:
        installed = self._scheduler.find(spec.name)
        return InstallPlan(spec, plan_for(spec, installed), installed)

    def install(self, spec: TaskSpec) -> InstallPlan:
        plan = self.plan(spec)
        if plan.action is not InstallAction.UNCHANGED:
            self._scheduler.register(spec)
        return plan

    def status(self, name: str) -> InstalledTask | None:
        return self._scheduler.find(name)

    def remove(self, name: str) -> bool:
        """Remove the task; False when there was none."""
        if self._scheduler.find(name) is None:
            return False
        self._scheduler.unregister(name)
        return True


_WILL = {
    InstallAction.CREATE: "This will create",
    InstallAction.UPDATE: "This will replace",
    InstallAction.UNCHANGED: "Nothing to do: already installed exactly like this,",
}
_DID = {
    InstallAction.CREATE: "Created",
    InstallAction.UPDATE: "Replaced",
    InstallAction.UNCHANGED: "Already installed, unchanged:",
}


def render_plan(plan: InstallPlan, *, done: bool) -> str:
    """What the task is (and was, if it is being replaced); `done` for after the change."""
    spec = plan.spec
    verb = (_DID if done else _WILL)[plan.action]
    lines = [
        f"{verb} Windows scheduled task {spec.name!r}:",
        f"  runs     daily at {spec.at.text}, as you, only while you are logged on",
        f"  command  {spec.command_line}",
    ]
    if plan.installed is not None and plan.action is InstallAction.UPDATE:
        at = plan.installed.at.text if plan.installed.at is not None else "no daily time"
        before = f"{plan.installed.program} {plan.installed.argument_text}".strip()
        lines.append(f"  was      daily at {at}: {before}")
    lines.append("  secrets  none stored; API keys are read from your user environment at run time")
    return "\n".join(lines)


def render_status(task: InstalledTask | None, name: str) -> str:
    if task is None:
        return f"not scheduled: no task named {name!r} (see `concert-tracker schedule install`)."
    at = f"daily at {task.at.text}" if task.at is not None else "no daily trigger"
    return f"scheduled: {name!r}, {at}\n  command  {task.program} {task.argument_text}".rstrip()
