# concert-tracker-adapter-lastfm

Last.fm over `httpx`, implementing core's `ArtistTagSource` (an artist's crowd-tag genres) and
`ListeningHistory` (the owner's play counts over the last 1, 3, 6 or 12 months).

- Key: `$CONCERT_TRACKER_LASTFM_KEY`; account name: `$CONCERT_TRACKER_LASTFM_USER`.
- Only the documented API is used (the API terms forbid gathering Last.fm data any other way) and
  only for personal, non-commercial use.
- Tag answers are cached locally in SQLite (a genre cache, never committed). Anything shown to other
  people must credit Last.fm with a link.
- Errors say what failed, never the request URL (it carries the key).
