"""Normalize a URL so two links to one page compare equal: no tracking params, fragment or trailing slashes."""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Strip UTM/tracking params, the fragment and trailing slashes from a URL; scheme and host lower-case."""
    try:
        parsed = urlparse(url)
        keep = {
            k: v
            for k, v in parse_qs(parsed.query).items()
            if not k.lower().startswith(("utm_", "ref", "source", "tracking"))
        }
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            urlencode(keep, doseq=True),
            "",
        ))
    except Exception:
        return url.strip().rstrip("/")
