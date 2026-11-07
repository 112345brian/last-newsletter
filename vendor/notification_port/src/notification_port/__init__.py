"""Send best-effort phone alerts: the port, the ntfy transport, and the pure spool/retry policy.

Install::

    notification_port @ git+https://github.com/112345brian/bripe-job-search.git@<sha>#subdirectory=libs/notification_port

- ``notification_port.notifier_port``: ``Notifier`` (what application code may ask of "something that pushes an alert") and
  the ``NotifyResult`` outcome a push returns.
- ``notification_port.transport``: ``NtfyTransport`` and the stdlib ``UrllibNtfyTransport``.
- ``notification_port.ntfy_policy``: request building, the redelivery-spool decisions and the flush loop; all take
  the time and the sender as arguments.

Standard library only; no environment, files or clock of its own.
"""
from notification_port.notifier_port import Notifier, NotifyResult
from notification_port.transport import NtfyTransport, UrllibNtfyTransport

__all__ = ["Notifier", "NotifyResult", "NtfyTransport", "UrllibNtfyTransport"]
