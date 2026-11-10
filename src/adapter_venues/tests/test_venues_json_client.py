from __future__ import annotations

import httpx
import pytest
from venue_fakes import served

from last_newsletter_adapter_venues import JsonClient
from last_newsletter_adapter_venues.client import MAX_BYTES
from last_newsletter_core.event_ports import SourceFetchError

_URL = "https://feed.example.com/data?token=SECRET-TOKEN"


def test_json_and_lower_cased_headers_come_back() -> None:
    client = JsonClient(http=served({"a": 1}, headers={"X-WP-TotalPages": "4"}))
    body, headers = client.get(_URL, {"page": "2"})
    assert body == {"a": 1}
    assert headers["x-wp-totalpages"] == "4"
    assert client.requests == 1


def test_query_parameters_are_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    JsonClient(http=httpx.Client(transport=httpx.MockTransport(handler))).get(
        "https://feed.example.com/x", {"page": "2", "per_page": "100"}
    )
    assert dict(seen[0].url.params) == {"page": "2", "per_page": "100"}


@pytest.mark.parametrize("status", [403, 404, 500])
def test_an_error_status_is_reported_with_its_code_and_without_the_url(status: int) -> None:
    with pytest.raises(SourceFetchError) as caught:
        JsonClient(http=served(b"", status)).get(_URL)
    assert str(status) in str(caught.value)
    assert "SECRET-TOKEN" not in str(caught.value)


def test_a_network_error_is_reported_by_type_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        message = f"failed for {request.url}"
        raise httpx.ConnectError(message)

    client = JsonClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(SourceFetchError) as caught:
        client.get(_URL)
    assert "ConnectError" in str(caught.value)
    assert "SECRET-TOKEN" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_body_that_is_not_json_is_an_error() -> None:
    with pytest.raises(SourceFetchError, match="did not return JSON"):
        JsonClient(http=served(b"<html>blocked</html>")).get(_URL)


def test_a_body_over_the_cap_is_refused() -> None:
    with pytest.raises(SourceFetchError, match="larger than"):
        JsonClient(http=served(b"x" * (MAX_BYTES + 10))).get(_URL)


def test_a_redirect_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://feed.example.com/new"})
        return httpx.Response(200, json={"ok": True})

    client = JsonClient(
        http=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )
    assert client.get("https://feed.example.com/old")[0] == {"ok": True}
