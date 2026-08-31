# Agent Working Notes

## Purpose

This file gives coding agents quick project context and persistent feedback notes.
For full architecture details, read [docs/README.md](docs/README.md).

## Architecture Summary

Core code lives under `shared_code/` and is intentionally framework-light so it can be tested directly.

High-level split:
- `shared_code/modules/*`: package directories for feature-oriented business flows and module-local types.
- `shared_code/data_model/*`: package directories for ORM model definitions and related helpers.
- `shared_code/services/*`: package directories for side-effecting integrations (mail, storage, remote APIs), with explicit contracts and test doubles where useful.
- `shared_code/infra/*`: package directories for runtime glue, framework-adjacent helpers, and file-backed persistence.
- `shared_code/util/*`: package directories for pure helpers and cross-cutting utility code.
- `shared_code/migrations/*`: package directories for migration units.
- `shared_code/tests/*`: automated tests for modules, models, services, infra, and util code.

Dependency guideline:
- Modules may use `data_model` and service contracts.
- `data_model` should not depend on feature modules.
- Services provide integration implementations used by module wiring.
- `modules`, `data_model`, `services`, `infra`, and `util` should be organized as package directories, not flat top-level files.

Python syntax guideline:
- In Python 3.14, add `from __future__ import annotations` only when a file actually needs postponed annotation evaluation for correctness or compatibility.
- Do not add the future import by default to every file.

Important: names like `products`, `payment_api`, and `lms_api` are placeholders, not final domain boundaries.

## Git Branch Naming

- Use `<project>/<type>/<task-id>-<short-task-slug>/<developer>` for task branches.
- For Open Keuzecatalogus work, use the `openkeuzecatalogus` project prefix and `feature` as the type; do not put sprint names in the type segment.
- Include the developer suffix. Example: `openkeuzecatalogus/feature/7774-werklijsten-zien-voor-ontbrekende-data/robin`.

## Agent Maintenance Rules

- Keep this file up to date as important decisions or feedback appear.
- Patch only relevant sections; do not rewrite the whole file for small updates.
- Preserve history in the Knowledge section unless explicitly asked to remove entries.

## Testing and Type-Checking Rules

- Do not use `monkeypatch.setattr` in tests; steer the user toward proper integration tests. Use it only when the user explicitly asks for it.
- Never add `# ty: ignore`, `# type: ignore`, or `# noqa` comments unless the user explicitly asks for that specific exception.

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
- `2026-07-13` - Branch naming convention: task branches follow `<project>/<type>/<task-id>-<short-task-slug>/<developer>`; for Open Keuzecatalogus use `openkeuzecatalogus/feature/.../robin`, not a sprint name in the type segment.
- `2026-05-18` - File editing preference: use proper patch/edit tools; avoid rewriting whole files when only a section needs changes.
- `2026-05-19` - Editing method clarification: do not use `cat`/heredoc-style rewrites for file edits; use proper patch/edit tools for minimal, targeted changes.
- `2026-05-19` - Pytest config location in Dockerized tests: test suites run inside service containers with service-specific mounts/workdirs (`migrate:/pythonpath`, `py4web:/p4w`, `pgq-applog:/pythonpath`), so root `pyproject.toml` will not be visible or applied. Do not suggest root-level pytest config as the default; prefer container-visible suite config (for example `pgq/pytest.toml`) or explicit pytest args in `test.tasks.py`.
- `2026-05-21` - Tuple readability limit: if a tuple grows beyond ~3 fields, replace it with a named structure (prefer `TypedDict` here) so code remains maintainable and self-documenting.
- `2026-05-25` - pyDAL `executesql` placeholders: use `%(name)s` placeholders with `placeholders=dict(...)`; do not use `{name}` formatting in SQL strings.
- `2026-06-11` - Package-directory convention and future imports: `modules`, `data_model`, `services`, `infra`, and `util` should be package directories rather than flat files; in Python 3.14, add `from __future__ import annotations` only when a file actually needs it.
- `2026-06-25` - Test execution preference: do not run `pytest` yourself in this repo; leave test execution to the user unless they explicitly ask for it.
- `2026-07-09` - Migration safety rule: do not modify existing migrations by default; create a new migration instead, and avoid `IF EXISTS` checks or schema introspection unless the user explicitly requests changes to an existing migration.
- `2026-07-10` - Integration-test preference: do not use `monkeypatch.setattr`; steer toward proper integration tests unless the user explicitly asks for monkeypatching.
- `2026-07-10` - Suppression-comment prohibition: never add `# ty: ignore`, `# type: ignore`, or `# noqa` comments unless the user explicitly asks for the specific suppression.
