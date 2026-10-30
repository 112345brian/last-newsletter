"""Composition root. Wires concrete adapters into the core use case and runs it.

This is the only module in the workspace allowed to import from every other
package. Nothing downstream of this file should ever import `last_newsletter_cli`.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from last_newsletter_adapter_email.imap_source import ImapConfig, ImapEmailSource
from last_newsletter_adapter_publish.markdown_publisher import MarkdownPublisher
from last_newsletter_adapter_summarizer.anthropic_summarizer import AnthropicSummarizer
from last_newsletter_core.entities import Cadence
from last_newsletter_core.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase


def _build_use_case() -> BuildDigestUseCase:
    email_source = ImapEmailSource(
        ImapConfig(
            host=os.environ["LAST_NEWSLETTER_IMAP_HOST"],
            username=os.environ["LAST_NEWSLETTER_IMAP_USER"],
            password=os.environ["LAST_NEWSLETTER_IMAP_PASSWORD"],
        )
    )
    summarizer = AnthropicSummarizer()
    publisher = MarkdownPublisher(output_dir=Path("digests"))
    return BuildDigestUseCase(email_source, summarizer, publisher)


def main() -> None:
    parser = argparse.ArgumentParser(prog="last-newsletter")
    parser.add_argument("--cadence", choices=["daily", "weekly"], default="weekly")
    args = parser.parse_args()

    cadence = Cadence(args.cadence)
    until = datetime.now(tz=UTC)
    since = until - (timedelta(days=1) if cadence is Cadence.DAILY else timedelta(days=7))

    use_case = _build_use_case()
    use_case.execute(BuildDigestRequest(since=since, until=until, cadence=cadence))


if __name__ == "__main__":
    main()
