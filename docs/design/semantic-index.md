> **Moved.** The index is `ngram_index` in [concert-tracker](https://github.com/112345brian/concert-tracker),
> vendored under `vendor/concert_tracker/` (it was `adapter_semantic` when this was written).

# Local similar-event index: decision note

**Need.** Match a new email's event against events already in the ledger without spending LLM tokens, offline, over thousands of events. A hit proposes a *possible duplicate* link only. It never merges (event-ledger.md sections 5 and 6).

## Options

| | (a) Hashed char n-gram vectors | (b) Local embedding model | (c) Both behind one port |
|---|---|---|---|
| Extra install | none (stdlib `sqlite3`, `zlib`) | model2vec: 54 MB of wheels (numpy, tokenizers, safetensors) plus an ~30 MB model; fastembed: 143 MB of wheels (onnxruntime) plus a ~70 MB model | (a) always, (b) opt-in extra |
| Cold start | measured, 3000 events: 60 ms load, 10 ms per query, 5 MB DB | not measured: needs a one-time model download, then a model load of about 0.1 to 1 s | as the chosen backend |
| Network | never | once, to fetch the model; none at query time if cached (`HF_HUB_OFFLINE=1`) | as above |
| Strength | typos, word order, `&` vs `and`, accents; same venue and entities | true paraphrase ("opening night" vs "season launch") | |
| Weakness | no synonyms | heavy dependency; slows `make check`; model version drift changes scores | one more seam to test |

At thousands of events a brute-force scan is enough for both, so no FTS5 and no `sqlite-vec`. FTS5 was dropped because it ranks by BM25, which is corpus-dependent, so a score for the same pair would drift as the corpus grows. The scan keeps scores stable and in [0, 1].

## Recommendation

- **Default: (a)**, `HashedNgramIndex` in `src/adapter_semantic`. Character 3-grams plus word hashes over title (weighted x2), venue, entities and tags; sublinear TF, L2-normalised, cosine; vectors persisted in SQLite so UUID to vector survives restarts. The date is a multiplier, not text: same day 1.0, unknown 0.85, any other day 0.45. No +-1 day tolerance: in the 19hz snapshot most repeated titles are consecutive-night runs, which are different events, so that tolerance stays in core's identity ladder.
- **Optional: (b) via model2vec** (smaller and faster than fastembed/ONNX), shipped later as an extra behind the same two-method port. Not built now: the labeled fixture shows no paraphrase misses at the default, and (b) would add a model download and a heavy install. Revisit when real data shows synonym misses.
- The port stays `index(event)` / `similar(candidate, *, limit)` so (c) needs no change in core.

## Threshold and measured quality

Threshold **0.60**, measured on two fixtures in `tests/fixtures/`:

| Fixture | Pairs | Same scores | Different scores | Precision | Recall |
|---|---|---|---|---|---|
| `event_pairs.json` (hand-written paraphrases) | 30 (15/15) | 0.67 to 1.00 | 0.00 to 0.54 | 1.00 | 1.00 |
| `event_pairs_19hz.json` (snapshot of 19hz.info Los Angeles, fetched once 2026-11-07, 575 rows) | 40 (20/20) | 0.84 to 1.00 | 0.05 to 0.45 | 1.00 | 1.00 |

In the 19hz fixture the different-event pairs are real rows (12 recurring nights with the same title and venue on different dates, 4 same-venue-same-day, 4 same-title-other-venue). The same-event pairs are real rows with a deterministic mechanical title change, because the page lists no duplicates. They are easy, so recall there is an upper bound. Both fixtures are small; 0.55 to 0.65 gives the same result. The nearest hand-written negative is 0.54, so re-measure on real mail.

## Safety properties

Never raises on blank, NUL, lone-surrogate or 200 KB text (text is NFKC-normalised, non-alphanumerics dropped, truncated to 2000 chars). Scores are rounded and ties break on id, so output is deterministic. The query excludes the candidate's own id.
