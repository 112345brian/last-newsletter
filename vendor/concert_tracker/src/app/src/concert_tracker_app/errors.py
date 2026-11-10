"""Errors a command reports to its user."""

from __future__ import annotations

__arbor__ = {"ring": "app"}


class ConfigError(Exception):
    """A setting is missing or invalid. Its message names the variable to fix."""
