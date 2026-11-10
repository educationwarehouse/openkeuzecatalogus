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

JavaScript code style:
- Use snake case for variables.
- Prefix HTML element variables with `$` and HTML element collections with `$$`.
- Use `data-*` attributes only to store data; do not use them as bootleg CSS classes or selectors.
- Use double quotes for strings, except when interpolating variables.
- Use arrow functions for inline callbacks and regular functions for named handlers.
- Always use braces `{}` for `if` blocks.
- For scripts that run multiple times (such as htmx responses), wrap the code in a block scope `{}` to avoid `const`/`let` redeclaration errors.
- Do not use IIFEs; use block scope instead.

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

- Browser tests must exercise real application routes, templates and widgets using prepared test records. Do not inject hand-written widget HTML, replace page content or fulfill successful application responses with duplicated markup. Test-only setup endpoints may prepare data, but must not render substitute pages or widgets. Request interception is appropriate for deliberate network failures or delays and external integrations, while successful application responses must come from the application.

- Do not use `monkeypatch.setattr` in tests; steer the user toward proper integration tests. Use it only when the user explicitly asks for it.
- Never add `# ty: ignore`, `# type: ignore`, or `# noqa` comments unless the user explicitly asks for that specific exception.
- This instruction applies only to code authored or edited by agents. It is not a code-review rule: do not report suppression comments as review findings.

## Code Style Rules

- Do not nest conditional expressions in Python or JavaScript/TypeScript. Use explicit `if`/`elif`/`else` or `if`/`else if`/`else` branches instead.
- Use `if`/`elif`/`else` (or `if`/`else if`/`else` in JavaScript/TypeScript) for mutually exclusive alternatives instead of repeated standalone `if` statements. Standalone `if` guard clauses are fine, but do not disguise an alternative-selection chain as repeated guards, even when each branch returns early.

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
- `2026-05-25` - pyDAL `executesql` parameterization: use supported parameterized t-strings (`t"..."`) where possible or `%(name)s` placeholders with a `placeholders` mapping. Both safely bind values. Do not interpolate SQL values with f-strings, `.format()`, or string concatenation.
- `2026-06-11` - Package-directory convention and future imports: `modules`, `data_model`, `services`, `infra`, and `util` should be package directories rather than flat files; in Python 3.14, add `from __future__ import annotations` only when a file actually needs it.
- `2026-06-25` - Test execution preference: do not run `pytest` yourself in this repo; leave test execution to the user unless they explicitly ask for it.
- `2026-07-09` - Migration safety rule: do not modify existing migrations by default; create a new migration instead, and avoid `IF EXISTS` checks or schema introspection unless the user explicitly requests changes to an existing migration.
- `2026-07-10` - Integration-test preference: do not use `monkeypatch.setattr`; steer toward proper integration tests unless the user explicitly asks for monkeypatching.
- `2026-07-10` - Suppression-comment prohibition: never add `# ty: ignore`, `# type: ignore`, or `# noqa` comments unless the user explicitly asks for the specific suppression.
- `2026-07-13` - Branch naming convention: task branches follow `<project>/<type>/<task-id>-<short-task-slug>/<developer>`; for Open Keuzecatalogus use `openkeuzecatalogus/feature/.../robin`, not a sprint name in the type segment.
- `2026-08-31` - Versioned migration-manager classes: when adding a `*ModelWithPrio_V*` class, use the established migration-manager scaffold and include `# noinspection PyPep8Naming` before every versioned class.
- `2026-09-16` - Design integration preserves functionality: Figma contains placeholders and is not a field inventory. Preserve existing fields, data, validation and actions even when absent from the design; audit the diff before delivery. Verify complete real-data user flows, reload persistence, modal layering and responsive interaction states on staging, not only initial screenshots.
- `2026-09-17` - TypeDAL query collections: do not call empty `.select()`, which is a no-op. Use `.collect()` for query results and `.first()` on the resulting collection when exactly one row is expected.
- `2026-09-24` - Query, decorator and HTML attribute style: use `.column(field)` instead of a row comprehension when only one field's values are needed; do not wrap a query collection in `list()` without a specific need; pass one HTTP method to `@action` as a string and multiple methods as a tuple; pass hyphenated YATL attributes through `convert_attrs`.
- `2026-10-05` - Review style corrections: do not prefix class names with an underscore. For effective-dated corrections, insert new `_ed` versions to establish the new `_model` truth; preserve existing historical rows.
- `2026-10-05` - Integration branch protection: agents must never merge into staging or sprint-draft branches. Merge the target branch into the feature branch when updating it; opening and babysitting a PR means monitoring checks and addressing feedback while leaving the PR open for the user to merge.
- `2026-10-06` - Superset exports are read-only: never edit files under `./superset/`. Use them only as references and document required live dashboard changes elsewhere.
- `2026-10-06` - Feedback log ordering: always keep dated entries in ascending chronological order, oldest first and newest last. Append entries for the same date after existing entries for that date.
- `2026-10-06` - Full-suite execution: ask the user to run the full suite instead of running or delegating it, including during PR delivery, to avoid unnecessary token costs.
- `2026-10-08` - Admin tile ordering and icons: append new tiles after existing tiles, preserving their order, and use an icon class backed by the SVG icon set.
- `2026-10-08` - Explicit ORM registration: never call `db.define` in a loop; define each table explicitly so its registration remains visible and independently configurable.
- `2026-10-29` - SQL parameterization clarification: parameterized t-strings, when supported, and named placeholders provide the same value-binding safety. Preserve existing safe SQL syntax rather than converting between them for style alone.
- `2026-10-29` - Extracted helper placement: prefer placing extracted helpers above the functions that call them so code follows its natural reading order.
- `2026-10-29` - Decorator readability: preserve `@decorator` syntax when extracting functions; do not replace decorated definitions with chained decorator-factory calls to reduce complexity scores. Extract a cohesive registration helper when needed.
- `2026-10-30` - Logical whitespace: separate logical chunks with blank lines, including input extraction, validation, lookups, state updates, successive loops and returns. Do not compress these into dense blocks just because the formatter permits it.
- `2026-11-05` - Dictionary merging: prefer `dict1 | dict2` over `{**dict1, **dict2}` when combining dictionaries.
