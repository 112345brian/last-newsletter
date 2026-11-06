# Vendored code

Copied, not depended on. Each directory under `vendor/` is a verbatim copy of a lib from the
owner's own `bripe-job-search` repo (`libs/<name>`), taken at commit `3f1d9bf9c26b72dd368edf8a972d57f38628f31f`
(`libs/` unchanged from `origin/main` `ede0b7c35` except the three added in that commit).
Nothing here installs from that repo. Edit the copies freely; this file records where they started.

| Directory | Source path | Third-party deps |
|---|---|---|
| urgency | libs/urgency | none |
| identity_dedupe | libs/identity_dedupe | none |
| source_dates | libs/source_dates | dateparser |
| text_normalize | libs/text_normalize | none |
| notification_port | libs/notification_port | none |
| usage_ledger_port | libs/usage_ledger_port | none |
| process_lock | libs/process_lock | filelock, tenacity |
| durable_outbox | libs/durable_outbox | psutil, process_lock |
| tracker_state | libs/tracker_state | none |

Rules: ruff and ty skip `vendor/`; import-linter and the workspace-layout test do not. `core` must
not import any of these (it owns its own defaults); they sit beside `core`, `text_match` and `mailtext` and are
used only through adapters.
