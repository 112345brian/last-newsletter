"""Composition root. Wires concrete adapters into the core use case and runs it.

This is the only module in the workspace allowed to import from every other
package. Nothing downstream of this file should ever import `last_newsletter_cli`.
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from last_newsletter_adapter_email.imap_source import ImapConfig, ImapEmailSource
from last_newsletter_adapter_knowledge import SqliteKnowledgeWeigher
from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from last_newsletter_adapter_summarizer.anthropic_summarizer import AnthropicSummarizer
from last_newsletter_adapter_web.app import create_app
from last_newsletter_core.entities import Cadence
from last_newsletter_core.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

if TYPE_CHECKING:
    from last_newsletter_core.ports import RelevanceWeigher

_DATA_DIR = Path.home() / ".last-newsletter"
_SERVE_PORT = 5317


def _digest_repository() -> JsonDigestRepository:
    return JsonDigestRepository(_DATA_DIR / "digests")


def _configured_weighers() -> list[RelevanceWeigher]:
    """Entirely opt-in: the generic program runs with none of these configured,
    and nothing about BuildDigestUseCase changes either way. Set
    LAST_NEWSLETTER_KNOWLEDGE_DB_PATH to turn this one on; add another env var
    and another `if` here for a future weigher, never by changing core."""
    weighers: list[RelevanceWeigher] = []
    knowledge_db_path = os.environ.get("LAST_NEWSLETTER_KNOWLEDGE_DB_PATH")
    if bool(knowledge_db_path):
        weighers.append(
            SqliteKnowledgeWeigher(
                Path(knowledge_db_path).expanduser(),
                subject_name=os.environ.get("LAST_NEWSLETTER_KNOWLEDGE_SUBJECT"),
            )
        )
    return weighers


def _build_use_case() -> BuildDigestUseCase:
    email_source = ImapEmailSource(
        ImapConfig(
            host=os.environ["LAST_NEWSLETTER_IMAP_HOST"],
            username=os.environ["LAST_NEWSLETTER_IMAP_USER"],
            password=os.environ["LAST_NEWSLETTER_IMAP_PASSWORD"],
        )
    )
    summarizer = AnthropicSummarizer()
    publisher = MarkdownPublisher(output_dir=_DATA_DIR / "markdown")
    return BuildDigestUseCase(
        email_source,
        summarizer,
        publisher,
        _digest_repository(),
        weighers=_configured_weighers(),
    )


def _run_build(cadence_name: str) -> None:
    cadence = Cadence(cadence_name)
    until = datetime.now(tz=UTC)
    since = until - (timedelta(days=1) if cadence is Cadence.DAILY else timedelta(days=7))

    use_case = _build_use_case()
    use_case.execute(BuildDigestRequest(since=since, until=until, cadence=cadence))


def _run_serve() -> None:
    """Foreground only: no background daemon, no proclaunch. You launch it (by
    double-clicking a launcher script or running this command) when you want to
    look at a digest, and close it when you're done — same as opening any other
    local app, nothing to keep alive in between."""
    app = create_app(_digest_repository())
    url = f"http://127.0.0.1:{_SERVE_PORT}/"
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=_SERVE_PORT, debug=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="last-newsletter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Fetch mail and write a new digest.")
    build_parser.add_argument("--cadence", choices=["daily", "weekly"], default="weekly")

    subparsers.add_parser("serve", help="Open the local digest browser in your web browser.")

    args = parser.parse_args()
    if args.command == "build":
        _run_build(args.cadence)
    elif args.command == "serve":
        _run_serve()


if __name__ == "__main__":
    main()
