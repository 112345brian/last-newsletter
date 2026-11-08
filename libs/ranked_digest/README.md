# ranked-digest

Build a ranked, continuity-aware digest over time:

```python
from ranked_digest import BuildDigestUseCase
from ranked_digest.use_cases.build_digest import BuildDigestRequest

use_case = BuildDigestUseCase(
    email_source=my_email_source,  # implements EmailSource
    summarizer=my_summarizer,  # implements Summarizer
    publisher=my_publisher,  # implements DigestPublisher
    repository=my_repository,  # implements DigestRepository
    weighers=[my_weigher],  # implements RelevanceWeigher, optional
)
digest = use_case.execute(BuildDigestRequest(since=..., until=..., cadence=...))
```

No I/O, no framework, no app-specific concept beyond the type names
(`EmailMessage`, `EmailSource`) that describe where items come from -- a
consumer outside the email/newsletter domain supplies its own `EmailSource`
and `Summarizer` and gets the same behavior:

- a theme with a known future date (a deadline) ranks by proximity to that
  date, with or without a fresh mention this period;
- a theme that keeps recurring across periods (`Theme.streak`) outranks an
  equally-covered one-off;
- any number of `RelevanceWeigher`s translate their own signal (a knowledge
  base, a listening history, anything) into a float added to a theme's
  ranking weight — zero configured is zero personalization;
- `source_count` is re-derived from the messages a theme actually cites,
  never taken on a Summarizer's say-so;
- continuity looks back exactly one preceding digest (via
  `DigestRepository.list_recent`), skipping a same-period re-run or an
  overlapping window so streaks don't inflate on a retry.
