# Prior art: taste from genres and artist similarity

Researched 2026-11-06. Web search plus two official pages read directly (Spotify's February 2026 migration guide, Last.fm's API terms as pasted by the owner). Everything not marked **[V]** is from search snippets or secondary sources and needs checking before it is relied on.

## Question

Can we crosswalk an artist to Spotify's genres (including odd micro-genres such as "escape room"), build a taste profile from the artists the owner already ranks highly, and use it to score new shows in the area?

## What exists

### Taste as a weighted tag vector (the standard method)
- Artist similarity by comparing sparse **tag weight vectors** with cosine similarity, sometimes compressed with latent semantic analysis, is the textbook content-based approach. Source: a Springer handbook chapter on music recommendation, and the Deldjoo, Schedl and Knees survey of content-driven music recommendation (47 articles, covers cold start). [arXiv 2107.11803](https://arxiv.org/pdf/2107.11803)
- Limits: artist or genre agreement is a coarse yes/no notion of similarity, and one cited result is that collaborative-filtering similarity predicts semantic tags better than content methods do (McFee, Barrington, Lanckriet). So tags are a good start, not the whole answer.
- Rare tags carrying more signal than common ones is what **IDF weighting** does. "Escape room" is a rare tag, so it would count for more than "pop". This is standard TF-IDF practice, not something I found a specific music paper for.

### Local event recommendation is published prior art
- **Localify** (2018): "Local Music Event Recommendation with Long Tail Artists" combines social tags with artist similarity to score artists, defines "local" as a small geographic area, and uses Bandsintown and aggregated event data. [arXiv 1809.02277](https://ar5iv.labs.arxiv.org/html/1809.02277)
- A follow-up on **popularity degradation bias** in local music recommendation. Local acts are long-tail, so popularity-ranked recommenders under-serve them. [ar5iv 2309.11671](https://ar5iv.labs.arxiv.org/html/2309.11671) Relevant: Spotify has removed `popularity` and `followers` from the Artist object for Development Mode apps **[V]**, and we should not rely on popularity anyway.
- Hobby projects (Concert Match, ShowHunter) do "related artists, then search an events API". Our case differs: the events are already in the mailbox.

### The "escape room" case
- "Escape room" is a genre Spotify's Glenn McDonald named himself for a cluster near trap and experimental indie R&B-pop. Spotify scores each artist's similarity to every genre, and the ranking is visible at Every Noise at Once. Sources: [The Fader](https://www.thefader.com/2020/12/02/escape-room-genre-spotify-unwrapped-explanation-every-noise-glenn-mcdonald), [Spotify for Artists](https://artists.spotify.com/blog/how-spotify-discovers-the-genres-of-tomorrow). About 5,000 genres around 2020. Whether Every Noise at Once is still updated: not found.
- Spotify genres are **artist-level**, not track-level. Such genres exist only in Spotify's vocabulary, so a crosswalk to other sources loses them (see below).

## What each source gives us

| Source | Gives | Terms and limits | Status |
|---|---|---|---|
| **Spotify Web API** | Artist `genres` (micro-genres), Search by name | **[V]** Feb 2026 migration guide: Development Mode apps need the app owner to hold Premium; 5 users per app; Client IDs per developer raised to 25 as of July 2026. Artist `followers` and `popularity` removed; **`genres` is not listed as removed** (page text has no mention of it). `GET /search` `limit` max is now 10, default 5. `GET /artists/{id}/top-tracks` removed, so no preview tracks through the API (embed player is separate). | A community thread reports empty or thin genre lists for some artists; unverified. Related-artists and recommendations endpoints were reported deprecated for new apps in 2024; **not verified here**. |
| **MusicBrainz** | Artist identity (MBID), genres and tags, URL relationships | Core data CC0; **tags and genres are supplementary data, CC BY-NC-SA 3.0**. About one request per second per IP and a descriptive `User-Agent` are required (official rate-limit page). Genres are community tags, so coverage of small artists varies. | No official Spotify-to-MBID table found. Whether artists carry a Spotify URL relationship, and how often, is unverified. mbspotify and SAMBL are community tools for the mapping. |
| **Last.fm** | Top tags per artist, **similar artists** (getSimilar) | **[V]** API terms (pasted): non-commercial use only; free for personal use; registered user and API key; credit Last.fm with the "powered by AudioScrobbler" button and link to artist pages; **pages using the API that are public need Last.fm's written approval**; stored data capped at 100 MB and cached per HTTP headers; delete everything on termination; must not gather data any other way (no scraping); Last.fm reserves a future revenue share. | I did not read the method pages, so response fields and weights are unconfirmed. Similarity there comes from listening behavior, which addresses the content-only limit above. |
| **Discogs, ListenBrainz, AcousticBrainz** | Styles, listening data, audio descriptors | not researched | out of scope for now |

## Findings that shape the design

1. **No single source reliably has genres for the small artists we most want.** Resident Advisor style acts may have no Spotify genres, thin MusicBrainz tags and a small Last.fm footprint. So the system needs a chain of sources and must report coverage honestly, with "no data" as a normal outcome.
2. **Spotify-only micro-genres do not translate.** MusicBrainz and Last.fm use different vocabularies. Mapping them onto Spotify's would need a hand-kept alias file (a GitHub project does this for Last.fm and MusicBrainz tags). Without it, keep tags in their source's namespace and compute similarity within one namespace at a time.
3. **The crosswalk is an identity problem, as with samples.** Artist name to Spotify id, MBID and Last.fm name has the same wrong-artist risk as Listen (same-name artists), so one resolver and one confirmation rule serve both features.
4. **Two signals are better than one.** Tag-vector cosine (content) plus Last.fm similar-to-a-liked-artist (behavioral) cover each other's weaknesses.
5. **Licenses constrain a public repo.** Last.fm and MusicBrainz tag data must not be committed here (tests use fakes), the app stays private and self-hosted, and each user supplies their own Last.fm key.
6. **Learning from behavior is still not researched.** Everything above builds a profile from preferences you already store in knowledge. How done, dismiss and snooze should update it (decay, bandits, avoiding a filter bubble) is open.

## Open questions

- What share of the owner's actual artists have at least one genre in Spotify, MusicBrainz and Last.fm? This must be measured on about 30 real names before choosing sources.
- Does `genres` still come back for a new Development Mode app, and for small artists?
- Does Last.fm `artist.getSimilar` still return usable data, and with what scores?
- Spotify's rules on caching artist metadata.
- Whether Every Noise at Once data can be used at all.
