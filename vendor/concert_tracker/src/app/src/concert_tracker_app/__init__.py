"""Concert Tracker's application layer: the logic a front end needs, with no front end in it.

This is what a command-line program, a script, or another project calls to work with the event
ledger: open it for writing under the one-writer lock (`ledger_session`), keep the similarity
index in step with it (`CoreSimilarIndex`, `sync_index`), and show what it holds (`render_text`,
`render_json`). It imports core and the ledger and index adapters, so it is the only library layer
that knows both; the source adapters (Ticketmaster and the rest) are not here, and the CLI package
is only argument parsing on top.

Another project that feeds events in (a mail reader, say) vendors this package together with core
and the two adapters, and so shares the same session and the same similarity policy instead of
copying them.
"""

__arbor__ = {"ring": "app"}

from concert_tracker_app.errors import ConfigError
from concert_tracker_app.events_view import render_json, render_text
from concert_tracker_app.ids import IdGenerator, Uuid4Ids
from concert_tracker_app.ledger_session import (
    INDEX_NAME,
    LEDGER_NAME,
    LedgerSession,
    copy_for_dry_run,
    ledger_session,
)
from concert_tracker_app.similarity import (
    LINK_ONLY_POLICY,
    CombinedSimilarIndex,
    CoreSimilarIndex,
    SimilarBackend,
    sync_index,
)

__all__ = [
    "INDEX_NAME",
    "LEDGER_NAME",
    "LINK_ONLY_POLICY",
    "CombinedSimilarIndex",
    "ConfigError",
    "CoreSimilarIndex",
    "IdGenerator",
    "LedgerSession",
    "SimilarBackend",
    "Uuid4Ids",
    "copy_for_dry_run",
    "ledger_session",
    "render_json",
    "render_text",
    "sync_index",
]
