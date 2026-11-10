"""Pure utility helpers shared across the codebase.

Every scope is a *package*: add `util/<scope>/__init__.py`, never a top-level
`util/<scope>.py`. Keeping one shape means a scope can grow into several modules (and pick up
its own tests or fixtures) without a rename that touches every import site.
"""
