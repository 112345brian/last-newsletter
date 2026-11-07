# notification_port

Best-effort phone alerts as a port, plus the ntfy transport and the pure spool/retry policy. Standard library only.

```
notification_port @ git+https://github.com/112345brian/bripe-job-search.git@<sha>#subdirectory=libs/notification_port
```

- `notification_port.notifier_port`: `Notifier` (Protocol) and `NotifyResult` (`bool(result)` is true only for `DELIVERED`).
- `notification_port.transport`: `NtfyTransport` and the stdlib `UrllibNtfyTransport`.
- `notification_port.ntfy_policy`: `build_publish_request`, `should_spool`, `spool_entry`, `bound_spool`, `flush_spool`.
  They take the server, topic, token, `now` and the re-send function as arguments; reading config, persisting the spool
  and logging are the caller's.
