from datetime import UTC, datetime

from last_newsletter_adapter_web.app import create_app
from ranked_digest.entities import Cadence, Digest, Theme


class FakeRepository:
    def __init__(self, digests: dict[str, Digest]) -> None:
        self._digests = digests

    def save(self, digest: Digest) -> str:
        raise NotImplementedError

    def list_recent(self, limit: int = 20) -> list[tuple[str, Digest]]:
        return list(self._digests.items())[:limit]

    def get(self, slug: str) -> Digest | None:
        return self._digests.get(slug)


def _digest() -> Digest:
    return Digest(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        cadence=Cadence.WEEKLY,
        themes=(Theme(title="AI agents", summary="four sources covered this", source_count=4),),
        total_messages=47,
        total_sources=23,
    )


def test_index_lists_digests() -> None:
    app = create_app(FakeRepository({"2026-01-01_weekly": _digest()}))
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/digests/2026-01-01_weekly"' in response.data
    assert b"weekly" in response.data
    assert b"47 messages" in response.data


def test_index_with_no_digests_shows_empty_state() -> None:
    app = create_app(FakeRepository({}))
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"No digests yet" in response.data


def test_digest_detail_shows_theme() -> None:
    app = create_app(FakeRepository({"2026-01-01_weekly": _digest()}))
    client = app.test_client()

    response = client.get("/digests/2026-01-01_weekly")

    assert response.status_code == 200
    assert b"AI agents" in response.data
    assert b"four sources covered this" in response.data


def test_digest_detail_missing_slug_is_404() -> None:
    app = create_app(FakeRepository({}))
    client = app.test_client()

    response = client.get("/digests/does-not-exist")

    assert response.status_code == 404
