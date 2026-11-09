from __future__ import annotations

import pytest
from tm_fakes import KEY, Clock, ScriptedTransport, ok, query_of

from last_newsletter_adapter_ticketmaster import HttpResponse, TicketmasterClient
from last_newsletter_adapter_ticketmaster.client import MIN_INTERVAL_S, parse_reset_seconds
from last_newsletter_core.event_ports import SourceFetchError


def _client(
    script: list[HttpResponse | Exception], clock: Clock | None = None
) -> tuple[TicketmasterClient, ScriptedTransport, Clock]:
    clock = clock or Clock()
    transport = ScriptedTransport(script)
    client = TicketmasterClient(
        KEY,
        transport=transport,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
    )
    return client, transport, clock


def _throttle_free(clock: Clock) -> list[float]:
    return [s for s in clock.sleeps if s > MIN_INTERVAL_S]


def test_a_page_is_requested_with_the_key_and_decoded() -> None:
    client, transport, _ = _client([ok({"page": {"totalElements": 0}})])
    assert client.get_page({"city": "Los Angeles"}) == {"page": {"totalElements": 0}}
    sent = query_of(transport.urls[0])
    assert sent["apikey"] == KEY
    assert sent["city"] == "Los Angeles"


def test_requests_are_spaced_under_the_per_second_limit() -> None:
    client, _, clock = _client([ok({}), ok({}), ok({})])
    for _ in range(3):
        client.get_page({})
    assert clock.sleeps == [MIN_INTERVAL_S, MIN_INTERVAL_S]
    assert client.requests == 3


def test_a_429_waits_for_the_reset_header_in_seconds_then_succeeds() -> None:
    limited = HttpResponse(429, b"{}", {"rate-limit-reset": "7"})
    client, transport, clock = _client([limited, ok({"done": True})])
    assert client.get_page({}) == {"done": True}
    assert len(transport.urls) == 2
    assert 7.5 in clock.sleeps


def test_a_429_reset_given_as_an_epoch_in_milliseconds_is_understood() -> None:
    clock = Clock()
    reset_ms = str(int((clock.wall + 10) * 1000))
    client, _, clock = _client(
        [HttpResponse(429, b"{}", {"rate-limit-reset": reset_ms}), ok({"x": 1})], clock
    )
    assert client.get_page({}) == {"x": 1}
    assert any(abs(s - 10.5) < 0.01 for s in clock.sleeps)


def test_a_429_with_no_header_backs_off_exponentially() -> None:
    client, _, clock = _client([HttpResponse(429, b"{}"), HttpResponse(429, b"{}"), ok({})])
    client.get_page({})
    assert _throttle_free(clock) == [1.5, 2.5]


def test_a_long_reset_means_the_daily_quota_is_spent_and_we_stop_instead_of_sleeping() -> None:
    limited = HttpResponse(429, b"{}", {"rate-limit-reset": "7200"})
    client, _, clock = _client([limited])
    with pytest.raises(SourceFetchError, match="daily quota"):
        client.get_page({})
    assert _throttle_free(clock) == []


def test_persistent_429_gives_up() -> None:
    client, transport, _ = _client([HttpResponse(429, b"{}")] * 4)
    with pytest.raises(SourceFetchError, match="429"):
        client.get_page({})
    assert len(transport.urls) == 4


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_is_named_without_echoing_it(status: int) -> None:
    client, _, _ = _client([HttpResponse(status, b"{}")])
    with pytest.raises(SourceFetchError) as caught:
        client.get_page({})
    assert str(status) in str(caught.value)
    assert KEY not in str(caught.value)


def test_a_network_error_never_leaks_the_url_or_key() -> None:
    boom = OSError(f"connection failed for https://x/events.json?apikey={KEY}")
    client, _, _ = _client([boom])
    with pytest.raises(SourceFetchError) as caught:
        client.get_page({})
    assert KEY not in str(caught.value)
    assert "apikey" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_a_server_error_is_retried_then_succeeds() -> None:
    client, transport, _ = _client([HttpResponse(503, b""), ok({"fine": 1})])
    assert client.get_page({}) == {"fine": 1}
    assert len(transport.urls) == 2


def test_a_persistent_server_error_gives_up_with_the_status() -> None:
    client, _, _ = _client([HttpResponse(500, b"")] * 4)
    with pytest.raises(SourceFetchError, match="HTTP 500"):
        client.get_page({})


def test_a_response_that_is_not_json_is_an_error() -> None:
    client, _, _ = _client([HttpResponse(200, b"<html>maintenance</html>")])
    with pytest.raises(SourceFetchError, match="not JSON"):
        client.get_page({})


def test_a_json_list_instead_of_an_object_is_an_error() -> None:
    client, _, _ = _client([HttpResponse(200, b"[1, 2]")])
    with pytest.raises(SourceFetchError, match="not JSON"):
        client.get_page({})


def test_a_blank_key_is_refused_up_front() -> None:
    with pytest.raises(SourceFetchError, match="empty"):
        TicketmasterClient("   ")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("5", 5.0), ("0", 0.0), ("1800000030", 30.0), ("1800000030000", 30.0), ("soon", None)],
)
def test_reset_header_forms(value: str, expected: float | None) -> None:
    assert parse_reset_seconds(value, now_epoch=1_800_000_000.0) == expected


def test_a_reset_in_the_past_means_no_wait() -> None:
    assert parse_reset_seconds("1700000000", now_epoch=1_800_000_000.0) == 0.0
