"""Guided integrations — connecting an API or a database without an engineer.

Two flows, both driven by the model reading real data and explaining it back
to the person before anything is saved:

* :mod:`payload` / :mod:`sources` — an HTTP endpoint is fetched, profiled and
  described; the person confirms; the result becomes a live lookup skill, a
  periodically refreshed knowledge document, or both.
* :mod:`dbsetup` — a database (login details, a SQLite file or a SQL dump) is
  connected, its schema is read and described; the assistant can then answer
  from it with guarded read-only queries.
"""
