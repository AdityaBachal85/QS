"""The application layer: persistence, HTTP API, and the UI it serves.

One process. It stores a project in one SQLite file and serves both the JSON API
and the browser UI, so running the platform is a single command with nothing to
install alongside it.

The engine is untouched by any of this -- it still imports nothing from here,
which is why swapping SQLite for Postgres later, or the UI for a different one,
costs nothing.
"""
