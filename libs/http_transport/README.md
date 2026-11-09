# http-transport

The workspace's single stdlib HTTP transport: `get` and `post` over `http.client`, with no
redirects, no proxies and no scheme surprises. Both return an `HttpResponse` (status, body,
lower-cased headers).

It exists so that the source adapters (Ticketmaster now, any feed or venue-calendar adapter next)
share one tested implementation instead of each carrying its own copy.

`libs/llmhost` deliberately keeps its own small transport: the `llm` ring may import only itself
(see `arborescent.toml`), so that the one place that talks to a model stays a self-contained leaf.
Callers depend on the narrow `Getter` or `Poster` protocol, never on `UrllibTransport`, so tests
pass a hand-written fake and open no socket.

It raises `OSError` (including `TimeoutError`) for network trouble and never includes a response
or URL in a message of its own; callers decide what is safe to report (a URL can hold a key).
