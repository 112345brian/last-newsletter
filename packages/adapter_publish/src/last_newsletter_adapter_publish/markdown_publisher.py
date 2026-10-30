"""Concrete DigestPublisher: renders a Digest to a Markdown file on disk.

Simplest possible output format to start; an HTML-email or static-feed publisher
can be added later as its own adapter package without touching core or this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from last_newsletter_core.entities import Digest


class MarkdownPublisher:
    """Implements last_newsletter_core.ports.DigestPublisher."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def publish(self, digest: Digest) -> None:
        msg = "Markdown rendering not yet implemented"
        raise NotImplementedError(msg)
