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
from last_newsletter_adapter_publish.email_publisher import (
    CompositePublisher,
    SmtpConfig,
    SmtpEmailPublisher,
)
from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from last_newsletter_adapter_summarizer.anthropic_summarizer import AnthropicSummarizer
from last_newsletter_adapter_summarizer.extractive_summarizer import ExtractiveSummarizer
from last_newsletter_adapter_web.app import create_app
from last_newsletter_core.entities import Cadence
from last_newsletter_core.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

if TYPE_CHECKING:
    from collections.abc import Mapping

    from last_newsletter_core.ports import DigestPublisher, RelevanceWeigher, Summarizer

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


class ConfigError(Exception):
    """A setting is missing or invalid. Its message names the variable to fix."""


def smtp_config_from_env(environ: Mapping[str, str]) -> SmtpConfig:
    def required(name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            msg = f"{name} is not set"
            raise ConfigError(msg)
        return value

    host = required("LAST_NEWSLETTER_SMTP_HOST")
    username = required("LAST_NEWSLETTER_SMTP_USER")
    password = required("LAST_NEWSLETTER_SMTP_PASSWORD")
    port_text = environ.get("LAST_NEWSLETTER_SMTP_PORT", "465")
    try:
        port = int(port_text)
    except ValueError:
        msg = f"LAST_NEWSLETTER_SMTP_PORT must be a number, got {port_text!r}"
        raise ConfigError(msg) from None
    sender = environ.get("LAST_NEWSLETTER_SMTP_FROM", username)
    try:
        return SmtpConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            sender=sender,
            recipient=environ.get("LAST_NEWSLETTER_SMTP_TO", sender),
            use_ssl=environ.get("LAST_NEWSLETTER_SMTP_SSL", "1") != "0",
        )
    except ValueError as error:
        raise ConfigError(str(error)) from error


def _summarizer(name: str) -> Summarizer:
    if name == "anthropic":
        return AnthropicSummarizer(
            provider=os.environ.get("LAST_NEWSLETTER_LLM_PROVIDER", "claude"),
            usage_ledger_path=_DATA_DIR / "usage.jsonl",
        )
    return ExtractiveSummarizer()


def _publisher(*, send: bool) -> DigestPublisher:
    markdown = MarkdownPublisher(output_dir=_DATA_DIR / "markdown")
    if not send:
        return markdown
    email = SmtpEmailPublisher(smtp_config_from_env(os.environ), sent_dir=_DATA_DIR / "sent")
    return CompositePublisher([markdown, email])


def _build_use_case(*, send: bool, summarizer: str) -> BuildDigestUseCase:
    email_source = ImapEmailSource(
        ImapConfig(
            host=os.environ["LAST_NEWSLETTER_IMAP_HOST"],
            username=os.environ["LAST_NEWSLETTER_IMAP_USER"],
            password=os.environ["LAST_NEWSLETTER_IMAP_PASSWORD"],
        )
    )
    return BuildDigestUseCase(
        email_source,
        _summarizer(summarizer),
        _publisher(send=send),
        _digest_repository(),
        weighers=_configured_weighers(),
    )


def _run_build(cadence_name: str, *, send: bool, summarizer: str) -> None:
    cadence = Cadence(cadence_name)
    # Aligned to UTC midnight, not "now": a re-run on the same day is the same period (same
    # slug, overwritten in place) instead of a new overlapping one that double-counts streaks.
    until = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    since = until - (timedelta(days=1) if cadence is Cadence.DAILY else timedelta(days=7))

    use_case = _build_use_case(send=send, summarizer=summarizer)
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
    build_parser.add_argument(
        "--send",
        action="store_true",
        help="Also email the digest (needs the LAST_NEWSLETTER_SMTP_* variables). "
        "A period is emailed at most once.",
    )
    build_parser.add_argument(
        "--summarizer",
        choices=["extractive", "anthropic"],
        default="extractive",
        help="extractive: no model, excerpts of each email (default).",
    )

    subparsers.add_parser("serve", help="Open the local digest browser in your web browser.")

    args = parser.parse_args()
    if args.command == "build":
        try:
            _run_build(args.cadence, send=args.send, summarizer=args.summarizer)
        except ConfigError as error:
            parser.exit(2, f"last-newsletter: {error}\n")
    elif args.command == "serve":
        _run_serve()


if __name__ == "__main__":
    main()
