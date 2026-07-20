# Testing

## Default Workflow

Use `edwh test.run` as the standard command to run all test suites.

This runs tests for:
- `shared_code`
- `py4web/tests` (inside `/p4w`)
- browser tests in `playwright/tests` (against running `py4web`)
- `pgq`
- migration runtime (`wipe db -> migrate -> coverage`)

It also generates coverage and reports aggregate coverage by default.

```bash
edwh test.run
```

## Common Options

`edwh test.run` supports these options:
- `--verbose`: pass `-v` to pytest
- `--show-output`: pass `-s` to pytest
- `--exitfirst`: stop on first failure (`-x`)
- `--keyword-search "<expr>"`: pytest `-k` expression
- `--extra "<args>"`: raw extra pytest args
- `--coverage`: enable/disable coverage (defaults to enabled)
  - disable explicitly with `--no-coverage`
- `TEST_PYTEST_DEFAULT_ARGS` (env var): default pytest args for direct `go-*` commands when no explicit pytest args are passed

Examples:

```bash
edwh test.run --verbose
edwh test.run --keyword-search "mail and not slow"
edwh test.run --exitfirst --show-output
edwh test.run --no-coverage

# default to `-s -v -x` on local machine for `go-*` commands
export TEST_PYTEST_DEFAULT_ARGS="-s -v -x"
```

## Suite-Specific Commands

Use these when you want to run a single suite:
- `edwh test.go-shared-code`
- `edwh test.go-py4web`
- `edwh test.go-web`
- `edwh test.go-pgq`
- `edwh test.go-migrate`
- `edwh test.report-html` (rebuild coverage HTML index from existing suite HTML reports)

You can also run coverage report aggregation directly:

```bash
edwh test.report
```

## Shared DB Fixtures

`shared_code/tests/conftest.py` provides reusable database fixtures for tests in `shared_code/tests`.

Core fixtures:
- `db_psql`: fresh Postgres `TypeDAL` per test.
- `db`: same connection with shared tables defined.

Lifecycle fixtures (function scope):
- `wipe_db`: drop all non-system schemas and return DAL.
- `run_migrations`: run pending migrations without wiping first.
- `migrated_db`: wipe first, then run migrations.

Lifecycle fixtures (file/module scope):
- `wipe_db_per_file`: wipe once per test file.
- `run_migrations_per_file`: migrate once per test file.
- `migrated_db_per_file`: composed wipe + migrate once per file.
- `db_per_file`: module-scoped DAL with tables defined after `migrated_db_per_file`.

Snapshot fixtures:
- `snapshot_session_per_file`: create a temporary `pg_dump` snapshot before first test in a file and restore on teardown.
- `snapshot_session`: same lifecycle, but once per full pytest session.
- `snapshot_name`: default snapshot directory name (`testing.snapshot`) used by `restored_db`.
- `restored_db`: wipe, restore snapshot from `/data/<snapshot_name>`, then run migrations.

Notes:
- Snapshot data lives under `/data` in containers (bind-mounted from `migrate/data`).
- `restored_db` expects `/data/<snapshot_name>` to exist and raises `FileNotFoundError` otherwise.
  If the directory exists but is empty, restoring will be skipped.

## Coverage Behavior

Coverage is collected per suite and written as JSON files under:
- `shared_cache/pytest/cov.01_shared_code.json`
- `shared_cache/pytest/cov.01_py4web.json`
- `shared_cache/pytest/cov.01_pgq.json`
- `shared_cache/pytest/cov.02_migrate.json`

For browser-driven tests against the running `py4web` service, runtime coverage can be captured from the web process itself:
- `edwh test.run` recreates `py4web` with
  `PY4WEB_COVERAGE_PROCESS_START=/p4w/coverage.py4web.toml`
  and `PY4WEB_COVERAGE_FILE=/shared_cache/pytest/.coverage.py4web.runtime`
  when coverage is enabled
- do not keep `PY4WEB_COVERAGE_PROCESS_START` permanently set in `.env`; keep it test-managed
- run browser tests with `edwh test.go-web`
- export/merge runtime data with `edwh test.py4web-runtime-coverage-report`
- this updates `shared_cache/pytest/cov.01_py4web.json` (single py4web report)

The shared coverage exclusions live in `shared_code/coverage.toml`.
They are reused by the containerized suites and the host-side `edwh test.go-tasks` path.

Py4web runtime coverage uses `py4web/coverage.py4web.toml` so web-driven coverage stays scoped to `apps` and `common`, and does not report `shared_code`.

When a file appears in multiple coverage reports, `edwh test.report` keeps the file entry from the highest-priority report based on numeric filename prefix (for example `02_*` overrides `01_*`).

`edwh test.report` aggregates those files into one combined summary and applies a threshold gate.
It also combines coverage data files and always writes an HTML report to:
- `shared_cache/pytest/htmlcov/index.html`

Default threshold:
- `80.0%`

Override threshold:

```bash
edwh test.report --min-coverage 85
```

If combined coverage is below the threshold, the command exits non-zero.

## Troubleshooting

- `No coverage json files found`: run `edwh test.run` (or individual suite commands with coverage enabled) before `edwh test.report`.
- Container-related failures: make sure the local environment and services are up (`edwh setup`, `edwh up`).
- Cache cleanup/permissions issues: `test.run` clears `shared_cache/pytest` and may need elevated permissions in your environment.
- Production safeguard: `test.*` tasks are blocked when `STATE_OF_DEVELOPMENT` is production-level.
- Database reset behavior: `test.run` invokes `test.go-migrate`, which removes `migrate/flags/migrate-*.complete` and recreates the `pg-0` volume (`docker compose down -v pg-0`), then boots `pg-0` and `redis-master` before running migrations.
