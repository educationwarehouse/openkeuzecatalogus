# Agent Working Notes

## Purpose

This file gives coding agents quick project context and persistent feedback notes.
For full architecture details, read [docs/README.md](docs/README.md).

## Architecture Summary

Core code lives under `shared_code/` and is intentionally framework-light so it can be tested directly.

High-level split:
- `shared_code/modules/*`: feature-oriented business flows and module-local types.
- `shared_code/data_model/*`: ORM model definitions.
- `shared_code/services/*`: side-effecting integrations (mail, storage, remote APIs), with explicit contracts and test doubles where useful.
- `shared_code/migrations/*`: migration units.
- `shared_code/tests/*`: automated tests for modules, models, and services.

Dependency guideline:
- Modules may use `data_model` and service contracts.
- `data_model` should not depend on feature modules.
- Services provide integration implementations used by module wiring.

Important: names like `products`, `payment_api`, and `lms_api` are placeholders, not final domain boundaries.

## Agent Maintenance Rules

- Keep this file up to date as important decisions or feedback appear.
- Patch only relevant sections; do not rewrite the whole file for small updates.
- Preserve history in the Knowledge section unless explicitly asked to remove entries.

## Knowledge Gained / Feedback Log

Use this section only for durable agent-behavior feedback from the user.
Do not log normal project decisions that are already captured in code/docs.

Include:
- Working-style constraints (for example editing preferences, review expectations).
- Repeated correction patterns that should change how agents operate.

Do not include:
- Feature/release architecture decisions documented elsewhere.
- Routine implementation updates or changelog-style notes.

Entry format:
- `YYYY-MM-DD` - Short title: what changed, why it matters, and what agents should do next time.

Entries:
- `2026-05-18` - File editing preference: use proper patch/edit tools; avoid rewriting whole files when only a section needs changes.
- `2026-05-19` - Editing method clarification: do not use `cat`/heredoc-style rewrites for file edits; use proper patch/edit tools for minimal, targeted changes.
- `2026-05-19` - Pytest config location in Dockerized tests: test suites run inside service containers with service-specific mounts/workdirs (`migrate:/pythonpath`, `py4web:/p4w`, `pgq-applog:/pythonpath`), so root `pyproject.toml` will not be visible or applied. Do not suggest root-level pytest config as the default; prefer container-visible suite config (for example `pgq/pytest.toml`) or explicit pytest args in `test.tasks.py`.
- `2026-05-21` - Tuple readability limit: if a tuple grows beyond ~3 fields, replace it with a named structure (prefer `TypedDict` here) so code remains maintainable and self-documenting.
- `2026-05-25` - pyDAL `executesql` placeholders: use `%(name)s` placeholders with `placeholders=dict(...)`; do not use `{name}` formatting in SQL strings.
