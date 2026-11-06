from datetime import UTC, date, datetime, timedelta

from last_newsletter_core.entities import Cadence, Digest, EmailMessage, Theme
from last_newsletter_core.use_cases.build_digest import BuildDigestRequest, BuildDigestUseCase

_TODAY = date(2026, 1, 8)
_UNTIL = datetime(2026, 1, 8, tzinfo=UTC)
_SINCE = datetime(2026, 1, 1, tzinfo=UTC)


class FakeEmailSource:
    def __init__(self, messages: list[EmailMessage]) -> None:
        self._messages = messages

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        return self._messages


class FakeSummarizer:
    """Records what it was called with; returns whatever the test configures,
    ignoring the real messages/prior_themes it was handed (that judgment call
    is exactly what a real Summarizer implementation is for)."""

    def __init__(self, themes: list[Theme]) -> None:
        self._themes = themes
        self.received_prior_themes: list[Theme] | None = None
        self.received_today: date | None = None

    def summarize(
        self, messages: list[EmailMessage], *, prior_themes: list[Theme], today: date
    ) -> list[Theme]:
        self.received_prior_themes = prior_themes
        self.received_today = today
        return self._themes


class FakeWeigher:
    """A stand-in for something that translates its own signal (a knowledge base, a
    listening history, anything) into a weight. Keyed by title for test simplicity."""

    def __init__(self, weights: dict[str, float]) -> None:
        self._weights = weights

    def weight_for(self, candidate: str) -> float:
        return self._weights.get(candidate, 0.0)


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: Digest | None = None

    def publish(self, digest: Digest) -> None:
        self.published = digest


class FakeRepository:
    def __init__(self, seed: list[Digest] | None = None) -> None:
        self._saved: list[Digest] = list(seed or [])
        self.list_recent_calls: list[int] = []

    def save(self, digest: Digest) -> str:
        self._saved.insert(0, digest)
        return f"slug-{len(self._saved)}"

    def list_recent(self, limit: int = 20) -> list[tuple[str, Digest]]:
        self.list_recent_calls.append(limit)
        return [(f"slug-{i}", d) for i, d in enumerate(self._saved[:limit])]

    def get(self, slug: str) -> Digest | None:
        raise NotImplementedError


def _message(source: str) -> EmailMessage:
    return EmailMessage(
        message_id=f"id-{source}",
        sender=f"{source}@example.com",
        subject="subject",
        received_at=_SINCE,
        body_text="body",
        source_label=source,
    )


def _request() -> BuildDigestRequest:
    return BuildDigestRequest(since=_SINCE, until=_UNTIL, cadence=Cadence.WEEKLY)


def test_dated_theme_outranks_a_more_covered_undated_theme() -> None:
    """A conference in 2 days should headline over a theme with more sources
    but no date — importance isn't just this period's source_count."""
    dated = Theme(
        title="Conference", summary="s", source_count=1, relevant_until=_TODAY + timedelta(days=2)
    )
    undated = Theme(title="Popular topic", summary="s", source_count=10)
    publisher = RecordingPublisher()
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([_message("a")]),
        summarizer=FakeSummarizer([undated, dated]),
        publisher=publisher,
        repository=FakeRepository(),
    )

    digest = use_case.execute(_request())

    assert [t.title for t in digest.themes] == ["Conference", "Popular topic"]


def test_an_expired_dated_theme_ranks_like_any_undated_one() -> None:
    expired = Theme(
        title="Past deadline",
        summary="s",
        source_count=1,
        relevant_until=_TODAY - timedelta(days=1),
    )
    undated = Theme(title="Popular topic", summary="s", source_count=10)
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([expired, undated]),
        publisher=RecordingPublisher(),
        repository=FakeRepository(),
    )

    digest = use_case.execute(_request())

    assert [t.title for t in digest.themes] == ["Popular topic", "Past deadline"]


def test_recurrence_streak_outranks_higher_single_period_source_count() -> None:
    recurring = Theme(title="Ongoing saga", summary="s", source_count=2, streak=4)
    fresh = Theme(title="New this week", summary="s", source_count=4, streak=1)
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([fresh, recurring]),
        publisher=RecordingPublisher(),
        repository=FakeRepository(),
    )

    digest = use_case.execute(_request())

    # recurring scores 5 (2 sources plus a 3-period streak bonus); fresh scores 4.
    assert [t.title for t in digest.themes] == ["Ongoing saga", "New this week"]


def test_a_weigher_can_make_a_less_covered_theme_outrank_a_more_covered_one() -> None:
    relevant = Theme(title="Band I like is playing", summary="s", source_count=2)
    generic = Theme(title="Generic newsletter topic", summary="s", source_count=4)
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([generic, relevant]),
        publisher=RecordingPublisher(),
        repository=FakeRepository(),
        weighers=[FakeWeigher({"Band I like is playing": 3.0})],
    )

    digest = use_case.execute(_request())

    # relevant scores 5 (2 sources plus a weight of 3); generic scores plain 4.
    assert [t.title for t in digest.themes] == [
        "Band I like is playing",
        "Generic newsletter topic",
    ]
    assert digest.themes[0].personal_weight == 3.0


def test_multiple_weighers_are_summed() -> None:
    theme = Theme(title="Multi-signal topic", summary="s", source_count=1)
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([theme]),
        publisher=RecordingPublisher(),
        repository=FakeRepository(),
        weighers=[
            FakeWeigher({"Multi-signal topic": 2.0}),
            FakeWeigher({"Multi-signal topic": 1.5}),
        ],
    )

    digest = use_case.execute(_request())

    assert digest.themes[0].personal_weight == 3.5


def test_a_small_weight_does_not_override_a_much_bigger_source_count() -> None:
    relevant_but_small = Theme(title="Small but relevant", summary="s", source_count=1)
    much_bigger = Theme(title="Much bigger topic", summary="s", source_count=20)
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([relevant_but_small, much_bigger]),
        publisher=RecordingPublisher(),
        repository=FakeRepository(),
        weighers=[FakeWeigher({"Small but relevant": 3.0})],
    )

    digest = use_case.execute(_request())

    assert [t.title for t in digest.themes] == ["Much bigger topic", "Small but relevant"]


def test_no_weighers_configured_leaves_personal_weight_at_zero() -> None:
    theme = Theme(title="Any topic", summary="s", source_count=1)
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([theme]),
        publisher=RecordingPublisher(),
        repository=FakeRepository(),
    )

    digest = use_case.execute(_request())

    assert digest.themes[0].personal_weight == 0.0


def test_only_still_eligible_prior_themes_are_offered_to_the_summarizer() -> None:
    expired = Theme(
        title="Expired", summary="s", source_count=1, relevant_until=_TODAY - timedelta(days=1)
    )
    upcoming = Theme(
        title="Upcoming", summary="s", source_count=1, relevant_until=_TODAY + timedelta(days=1)
    )
    undated = Theme(title="Recurring, no date", summary="s", source_count=1)
    prior_digest = Digest(
        period_start=_SINCE - timedelta(days=7),
        period_end=_SINCE,
        cadence=Cadence.WEEKLY,
        themes=(expired, upcoming, undated),
        total_messages=3,
        total_sources=3,
    )
    summarizer = FakeSummarizer([])
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=summarizer,
        publisher=RecordingPublisher(),
        repository=FakeRepository(seed=[prior_digest]),
    )

    use_case.execute(_request())

    assert summarizer.received_prior_themes == [upcoming, undated]
    assert summarizer.received_today == _TODAY


def test_execute_saves_the_built_digest_to_the_repository() -> None:
    publisher = RecordingPublisher()
    repository = FakeRepository()
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([_message("a")]),
        summarizer=FakeSummarizer([]),
        publisher=publisher,
        repository=repository,
    )

    digest = use_case.execute(_request())

    assert repository.list_recent(limit=1) == [("slug-0", digest)]
    assert publisher.published is digest


def test_execute_with_no_messages_still_publishes_empty_digest() -> None:
    publisher = RecordingPublisher()
    use_case = BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=FakeSummarizer([]),
        publisher=publisher,
        repository=FakeRepository(),
    )

    digest = use_case.execute(_request())

    assert digest.themes == ()
    assert digest.total_messages == 0
    assert publisher.published is digest


def _theme_citing(ids: tuple[str, ...], source_count: int, *, carried: bool = False) -> Theme:
    return Theme(
        title="T",
        summary="s",
        source_count=source_count,
        source_message_ids=ids,
        carried_forward=carried,
    )


def _build(
    messages: list[EmailMessage], themes: list[Theme], repo: FakeRepository | None = None
) -> Digest:
    return BuildDigestUseCase(
        email_source=FakeEmailSource(messages),
        summarizer=FakeSummarizer(themes),
        publisher=RecordingPublisher(),
        repository=repo or FakeRepository(),
    ).execute(_request())


def test_source_count_is_derived_from_the_cited_messages_not_the_summarizers_claim() -> None:
    digest = _build([_message("a")], [_theme_citing(("id-a",), source_count=9)])

    assert digest.themes[0].source_count == 1


def test_two_messages_from_one_source_count_as_one_source() -> None:
    first = _message("a")
    second = EmailMessage("id-a2", "a@example.com", "s2", _SINCE, "b", "a")

    digest = _build([first, second], [_theme_citing(("id-a", "id-a2"), source_count=2)])

    assert digest.themes[0].source_count == 1


def test_hallucinated_message_ids_are_ignored() -> None:
    digest = _build(
        [_message("a"), _message("b")],
        [_theme_citing(("id-a", "id-b", "id-nope"), source_count=3)],
    )

    assert digest.themes[0].source_count == 2


def test_a_blank_source_label_falls_back_to_the_sender() -> None:
    blank = EmailMessage("id-x", "x@example.com", "s", _SINCE, "b", "")
    other = EmailMessage("id-y", "y@example.com", "s", _SINCE, "b", "")

    digest = _build([blank, other], [_theme_citing(("id-x", "id-y"), source_count=1)])

    assert digest.themes[0].source_count == 2


def test_an_unverifiable_claim_is_capped_at_the_sources_actually_seen() -> None:
    digest = _build([_message("a")], [_theme_citing((), source_count=9)])

    assert digest.themes[0].source_count == 1


def test_a_carried_forward_theme_with_no_new_mentions_keeps_its_count() -> None:
    digest = _build([_message("a")], [_theme_citing(("old-id",), source_count=4, carried=True)])

    assert digest.themes[0].source_count == 4


def test_messages_at_or_after_the_window_end_are_not_part_of_this_digest() -> None:
    inside = _message("a")
    at_end = EmailMessage("id-end", "e@example.com", "s", _UNTIL, "b", "e")
    after = EmailMessage("id-late", "l@example.com", "s", _UNTIL + timedelta(hours=3), "b", "l")

    digest = _build([inside, at_end, after], [])

    assert digest.total_messages == 1
    assert digest.total_sources == 1


def _digest_over(start: datetime, end: datetime, cadence: Cadence, theme: Theme) -> Digest:
    return Digest(
        period_start=start,
        period_end=end,
        cadence=cadence,
        themes=(theme,),
        total_messages=1,
        total_sources=1,
    )


def test_a_digest_for_the_same_period_is_not_offered_back_as_prior_history() -> None:
    """Re-running a build for a period must not feed that period's own earlier result
    back in as 'last period', or every re-run would bump the streak again."""
    earlier_run = _digest_over(_SINCE, _UNTIL, Cadence.WEEKLY, Theme("Saga", "s", 1, streak=1))
    summarizer = FakeSummarizer([])
    BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=summarizer,
        publisher=RecordingPublisher(),
        repository=FakeRepository(seed=[earlier_run]),
    ).execute(_request())

    assert summarizer.received_prior_themes == []


def test_an_overlapping_digest_is_skipped_for_the_most_recent_one_that_tiles() -> None:
    tiles = _digest_over(_SINCE - timedelta(days=7), _SINCE, Cadence.WEEKLY, Theme("Prior", "s", 1))
    overlaps = _digest_over(
        _SINCE + timedelta(days=1),
        _UNTIL + timedelta(days=1),
        Cadence.WEEKLY,
        Theme("Over", "s", 1),
    )
    summarizer = FakeSummarizer([])
    BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=summarizer,
        publisher=RecordingPublisher(),
        repository=FakeRepository(seed=[overlaps, tiles]),
    ).execute(_request())

    assert [t.title for t in summarizer.received_prior_themes or []] == ["Prior"]


def test_a_prior_digest_of_a_different_cadence_is_not_continuity() -> None:
    daily = _digest_over(_SINCE - timedelta(days=1), _SINCE, Cadence.DAILY, Theme("Daily", "s", 1))
    summarizer = FakeSummarizer([])
    BuildDigestUseCase(
        email_source=FakeEmailSource([]),
        summarizer=summarizer,
        publisher=RecordingPublisher(),
        repository=FakeRepository(seed=[daily]),
    ).execute(_request())

    assert summarizer.received_prior_themes == []
