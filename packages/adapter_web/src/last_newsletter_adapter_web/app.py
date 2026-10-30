"""Read-only local digest browser.

Depends only on `last_newsletter_core.ports.DigestRepository` — it has no idea
whether digests live in JSON files, SQLite, or anywhere else. Run via the CLI's
`last-newsletter serve`; there is no deploy target, no account system, nothing
running except this one process on localhost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Flask, abort, render_template_string

if TYPE_CHECKING:
    from last_newsletter_core.ports import DigestRepository

_INDEX_TEMPLATE = """
<!doctype html>
<title>Last Newsletter</title>
<h1>Digests</h1>
{% if digests %}
<ul>
  {% for slug, digest in digests %}
  <li>
    <a href="/digests/{{ slug }}">
      {{ digest.cadence.value }} —
      {{ digest.period_start.date() }} to {{ digest.period_end.date() }}
    </a>
    ({{ digest.themes|length }} themes, {{ digest.total_messages }} messages from
    {{ digest.total_sources }} sources)
  </li>
  {% endfor %}
</ul>
{% else %}
<p>No digests yet. Run <code>last-newsletter build</code> first.</p>
{% endif %}
"""

_DIGEST_TEMPLATE = """
<!doctype html>
<title>{{ digest.cadence.value }} digest — {{ digest.period_start.date() }}</title>
<p><a href="/">&larr; all digests</a></p>
<h1>
  {{ digest.cadence.value|capitalize }} digest:
  {{ digest.period_start.date() }} to {{ digest.period_end.date() }}
</h1>
<p>{{ digest.total_messages }} messages from {{ digest.total_sources }} sources.</p>
{% for theme in digest.themes %}
<h2>{{ theme.title }} <small>({{ theme.source_count }} sources)</small></h2>
<p>{{ theme.summary }}</p>
{% endfor %}
"""


def create_app(repository: DigestRepository) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        return render_template_string(_INDEX_TEMPLATE, digests=repository.list_recent())

    @app.get("/digests/<slug>")
    def digest_detail(slug: str) -> str:
        digest = repository.get(slug)
        if digest is None:
            abort(404)
        return render_template_string(_DIGEST_TEMPLATE, digest=digest)

    return app
