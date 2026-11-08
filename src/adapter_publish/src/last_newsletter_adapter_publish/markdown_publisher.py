"""Concrete DigestPublisher: renders a Digest to a Markdown file on disk.

Simplest possible output format to start; an HTML-email or static-feed publisher
can be added later as its own adapter package without touching core or this one.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from typing import TYPE_CHECKING

from last_newsletter_adapter_publish.render import render_markdown
from last_newsletter_core.entities import digest_slug

if TYPE_CHECKING:
    from pathlib import Path

    from last_newsletter_core.entities import Digest
    from last_newsletter_core.use_cases.list_upcoming_events import UpcomingEvents


class MarkdownPublisher:
    """Implements last_newsletter_core.ports.DigestPublisher."""

    def __init__(self, output_dir: Path, *, upcoming: UpcomingEvents | None = None) -> None:
        """`upcoming` is the "Coming up" window to print above the themes; None omits it."""
        self._upcoming = upcoming
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, digest: Digest) -> None:
        path = self._output_dir / f"{digest_slug(digest)}.md"
        path.write_text(render_markdown(digest, self._upcoming))
