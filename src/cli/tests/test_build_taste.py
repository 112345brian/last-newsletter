"""`build --genre/--listened/--rank/--taste`: Last.fm in the Coming up section, never unasked."""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import httpx
import pytest
from concert_tracker_core.events import AllDay, EntityRef, EntityRole, Event
from test_build_coming_up import _NOW, _event, _raw_mail, make_ledger

cli_main = importlib.import_module("last_newsletter_cli.main")
taste_section = importlib.import_module("last_newsletter_cli.taste_section")
_LA = "America/Los_Angeles"
_KEY = "test-key-not-real"
_TAGS = {
    "Punk Band": [{"name": "punk", "count": 100}],
    "Jazz Trio": [{"name": "jazz", "count": 100}],
}
_PLAYS = {"Jazz Trio": 40, "Punk Band": 3}


def _billed(n: int, title: str, artist: str) -> Event:
    entities = (EntityRef(artist, EntityRole.HEADLINER),) if artist else ()
    return _event(n, AllDay(date(2026, 11, 12)), title, entities=entities)


class FakeLastfm:
    def __init__(self) -> None:
        self.methods: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params)
        self.methods.append(query["method"])
        if query["method"] == "artist.gettoptags":
            tags = _TAGS.get(query["artist"])
            if tags is None:
                return httpx.Response(200, json={"error": 6, "message": "not found"})
            return httpx.Response(200, json={"toptags": {"tag": tags}})
        artists = [{"name": n, "playcount": str(p)} for n, p in _PLAYS.items()]
        return httpx.Response(
            200, json={"topartists": {"artist": artists, "@attr": {"totalPages": "1"}}}
        )


def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def lastfm(monkeypatch: pytest.MonkeyPatch) -> FakeLastfm:
    server = FakeLastfm()
    real = taste_section.LastfmClient

    def client(key: str) -> object:
        return real(key, http=httpx.Client(transport=httpx.MockTransport(server)), sleep=_no_sleep)

    monkeypatch.setattr(taste_section, "LastfmClient", client)
    monkeypatch.setenv(taste_section.KEY_VARIABLE, _KEY)
    monkeypatch.setenv(taste_section.USER_VARIABLE, "someone")
    return server


@pytest.fixture
def billed_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli_main, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(cli_main, "_now", lambda: _NOW)
    _raw_mail(tmp_path)
    make_ledger(
        tmp_path,
        [
            _billed(1, "Punk Show", "Punk Band"),
            _billed(2, "Jazz Night", "Jazz Trio"),
            _billed(3, "Mystery", "Who Dis"),
            _billed(4, "Billless", ""),
        ],
    )
    return tmp_path


def _build(data_dir: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[str, str, str]:
    capsys.readouterr()
    cli_main.main(["build", "--home-tz", _LA, *args])
    captured = capsys.readouterr()
    [path] = sorted((data_dir / "markdown").glob("*.md"))
    return captured.out, captured.err, path.read_text(encoding="utf-8")


def test_without_taste_options_last_fm_is_never_touched(
    billed_ledger: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_: str) -> None:
        pytest.fail("Last.fm was contacted without a taste option")

    monkeypatch.setattr(taste_section, "LastfmClient", forbidden)
    monkeypatch.delenv(taste_section.KEY_VARIABLE, raising=False)
    out, err, md = _build(billed_ledger, capsys)
    assert err == ""
    assert "Punk Show" in md
    assert "Last.fm" not in md
    assert "genres unknown" not in out
    assert not (billed_ledger / taste_section.CACHE_PATH).exists()


@pytest.mark.usefixtures("lastfm")
def test_genre_keeps_matches_counts_the_unknown_and_credits_last_fm(
    billed_ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, _, md = _build(billed_ledger, capsys, "--genre", "punk")
    assert "Punk Show" in md
    assert "*punk*" in md
    assert "Jazz Night" not in md
    assert "[Last.fm](https://www.last.fm)" in md
    assert "2 more not shown: artists' genres unknown" in out  # Who Dis, Billless
    assert (billed_ledger / taste_section.CACHE_PATH).exists()


def test_rank_puts_the_most_listened_first_and_shows_plays(
    billed_ledger: Path, capsys: pytest.CaptureFixture[str], lastfm: FakeLastfm
) -> None:
    _, _, md = _build(billed_ledger, capsys, "--rank")
    assert md.index("Jazz Night") < md.index("Punk Show")
    assert "★ 40 plays" in md
    assert set(lastfm.methods) == {"user.gettopartists"}


@pytest.mark.usefixtures("lastfm")
def test_listened_keeps_only_artists_played_that_often(
    billed_ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, md = _build(billed_ledger, capsys, "--listened", "10")
    assert "Jazz Night" in md
    assert "Punk Show" not in md


@pytest.mark.usefixtures("lastfm")
def test_filtering_everything_out_omits_the_section_and_says_why(
    billed_ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, _, md = _build(billed_ledger, capsys, "--genre", "polka")
    assert "Coming up" not in md
    assert "section omitted" in out
    assert "more not shown: artists' genres unknown" in out


@pytest.mark.usefixtures("billed_ledger")
@pytest.mark.parametrize("option", [["--genre", "punk"], ["--rank"], ["--taste"]])
def test_a_missing_key_stops_the_build_naming_the_variable(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    option: list[str],
) -> None:
    monkeypatch.delenv(taste_section.KEY_VARIABLE, raising=False)
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["build", "--home-tz", _LA, *option])
    assert stop.value.code == 2
    assert taste_section.KEY_VARIABLE in capsys.readouterr().err


@pytest.mark.usefixtures("billed_ledger")
def test_listening_without_a_user_name_stops_the_build(
    capsys: pytest.CaptureFixture[str],
    lastfm: FakeLastfm,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(taste_section.USER_VARIABLE)
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["build", "--home-tz", _LA, "--rank"])
    assert stop.value.code == 2
    assert taste_section.USER_VARIABLE in capsys.readouterr().err
    assert lastfm.methods == []


@pytest.mark.usefixtures("billed_ledger")
def test_a_refused_key_stops_the_build_without_printing_the_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": 10, "message": "Invalid API key"})

    real = taste_section.LastfmClient
    monkeypatch.setattr(
        taste_section,
        "LastfmClient",
        lambda key: real(
            key, http=httpx.Client(transport=httpx.MockTransport(refuse)), sleep=_no_sleep
        ),
    )
    monkeypatch.setenv(taste_section.KEY_VARIABLE, _KEY)
    with pytest.raises(SystemExit) as stop:
        cli_main.main(["build", "--home-tz", _LA, "--taste"])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "key was refused" in err
    assert _KEY not in err


def test_every_module_that_narrows_by_taste_reports_what_it_hid() -> None:
    """A genre filter hides events; the line `build` prints comes from `describe_included`, which
    reads `taste_unknown_hidden`. Scan the callers, not a reminder."""
    root = Path(cli_main.__file__).parent
    offenders = [
        str(path)
        for path in root.rglob("*.py")
        if "with_taste(" in (text := path.read_text(encoding="utf-8"))
        and "describe_included" not in text
    ]
    assert offenders == []
    described = (root / "upcoming_section.py").read_text(encoding="utf-8")
    assert "taste_unknown_hidden" in described
