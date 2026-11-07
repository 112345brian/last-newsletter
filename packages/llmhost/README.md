# llmhost

One call to get a structured response out of an LLM, with the token usage
that cost recorded:

```python
from pathlib import Path
from llmhost import resolve, record_usage

provider = resolve("claude")  # the only provider implemented so far
result = provider.complete_with_tool(
    model="claude-sonnet-5-5",
    system="...",
    user_message="...",
    tool_schema={...},  # a standard Anthropic tool JSON schema
    tool_name="record_themes",
    max_tokens=4096,
)
record_usage(Path("usage.jsonl"), provider="claude", purpose="summarize", usage=result.usage)
```

`resolve()` is a registry, not a single hardcoded provider — add
`provider_openai.py` (same shape as `provider_claude.py`) and register it in
`providers.py` to add a second one; nothing calling `resolve()` changes.

No newsletter, no IMAP, no app-specific concept anywhere in it — just the
provider call and the usage ledger.
