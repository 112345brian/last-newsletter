# usage_ledger_port

The LLM usage ledger as a budget gate sees it. Standard library only.

```
usage_ledger_port @ git+https://github.com/112345brian/bripe-job-search.git@<sha>#subdirectory=libs/usage_ledger_port
```

- `UsageLedger` (Protocol): `load_rows()` and `record_budget_skip(...)`.
- `UsageLedgerSlot`: holds the bound ledger; `get()` raises `UsageLedgerNotBound` when none is, so an unbound process
  cannot read "no spend". The application creates the slot and decides who binds it.
