# Testing

## Default Workflow

Use `edwh test.run` as the standard command to run all test suites.

This runs tests for:
- `shared_code`
- shared py4web tests in `py4web/tests` (inside `/p4w`)
- app-local py4web tests in `py4web/apps/*/tests`
- browser tests in `playwright/tests` (against running `py4web`)
- `pgq`
- migration runtime (`wipe db -> migrate -> coverage`)

It also generates coverage and reports aggregate coverage by default.

Database resets remove the web containers and all PGQ worker/scheduler containers before replacing PostgreSQL. Disposable-database cleanup removes those clients too, so later runs cannot reuse unhealthy workers or connections to a previous test database.

```bash
edwh test.run
```

In `ONT`, the full run stops on the first failure by default, both within pytest
and before starting another suite. Use `edwh test.run --no-exitfirst` to continue
through all suites instead. In `TEST`, continuing through all suites remains the
default; use `edwh test.run --exitfirst` to stop on the first failure.
These defaults use the host's `STATE_OF_DEVELOPMENT`, before the runner sets the
container test environment.

## Common Options

`edwh test.run` supports these options:
- `--verbose`: pass `-v` to pytest
- `--show-output`: pass `-s` to pytest
- `--exitfirst`: stop on first failure (`-x`); enabled by default in `ONT`
  - `--no-exitfirst`: disable the default in `ONT`
- `--keyword-search "<expr>"`: pytest `-k` expression
- `--extra "<args>"`: shell-style extra pytest args, split into individual arguments
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

## Profiling and Performance

Use pytest's duration reporting to inspect test calls, fixture setup and teardown:

```bash
edwh test.run --show-output --extra='--durations=20 --durations-min=0.1'
```

Keep `--show-output` when profiling the full suite: the host task test launches an Invoke subprocess
that needs uncaptured stdin. The runner preserves its existing reporting markers and does not add
per-suite timing lines to stdout.

When the migration suite is selected, its covered migration run initializes the disposable database,
avoiding a redundant uncovered migration run. Standalone commands and suite selections without
migrations still initialize their database. Browser tests retain a separate reset with catalogue
configuration seeding.

To evaluate further speedups, compare complete runs with the same configuration and retain their raw
coverage data and JSON reports. Check executed cases, skip reasons, source-file sets, covered lines
and executed branch arcs, rather than relying on the aggregate percentage alone. Repeat measurements
to account for host load and compare cold and warm runs separately.

Preserve database, migration, browser and side-effect isolation when optimizing the runner.
Keep report files writable by host and container users, and merge every worker's coverage.

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

The `playwright` Compose service uses the `test` profile, so plain `docker compose up` excludes it.
Browser test tasks explicitly run that service and do not require enabling the profile manually.
An existing edwh `.toml` that explicitly includes `playwright` in its minimal service list will still start it;
remove it from that list if you want `edwh up` to exclude it too.

## Load Testing

`edwh test.load` runs public Locust journeys separately from `test.run`. The Compose `load` service uses a pinned
Locust image and a `load` profile, so normal stack startup does not start a load generator.
The workload files live in `locust/`, mounted read-only at `/mnt/locust`.

Start with a configured, migrated development stack containing representative catalogue data:

```bash
edwh test.load
edwh test.load --users 50 --spawn-rate 5 --run-time 5m
edwh test.load --web
```

The default is a headless one-minute run with 100 users, spawning 10 users per second, against `http://py4web:8000`.
Compose starts local dependencies and waits for py4web to be healthy. This task uses the existing database and does
not seed or reset it. Each visitor pauses between actions, so the user count is not a requests-per-second target.

`--web` opens Locust's interactive mode at `http://localhost:8089`; use `--port 8090` to change the host port.
Start and stop runs in the UI. `--run-time` applies to headless runs only. CSV statistics, failure details, request
history and the HTML report are written to `shared_cache/load/` and overwritten by subsequent runs. Failed requests
produce a non-zero exit status in headless mode.

The task runs the container as `1050:1050`, matching the `microservices` ownership used by project setup.
It checks host-side report write permissions before starting Locust. If this check fails, correct the
ownership/group permissions of `shared_cache/load/` and any existing report files.

To target a separate environment explicitly:

```bash
edwh test.load --host https://your-test-environment.example --users 20 --run-time 2m
```

An explicit remote host skips local dependencies. TLS verification stays enabled. The existing production-state
guard also applies to this task.

The journeys adapt the [Hugo load-test scenario](https://github.com/educationwarehouse/openkeuzecatalogus-load-tests/tree/hugo)
to this application's routes. They cover general pages, method and product overviews, initial HTMX filter requests,
likely-hit and intentional-miss searches, filter and sort changes, list/grid views, filter clearing, option search
and pagination for large filters, result pagination, discovered detail pages and comparisons. Filter values and IDs
come from the current responses rather than a hardcoded dataset. Empty search results are valid; missing result counts,
missing filter controls, unexpected redirects and HTTP errors count as failures.

Same-origin scripts, stylesheets and up to eight images per response are requested once per visitor. This is an HTTP
workload, not a full browser simulation: it does not execute JavaScript, load CSS subresources or contact external image
hosts. Records and next pages must exist in the target data for those follow-up requests to run. Authentication and
private write flows are outside this public scenario.

## Py4web Test Placement

Put tests that apply to shared py4web code or multiple apps in `py4web/tests`.
Put app-specific tests in that app's `tests` directory, for example
`py4web/apps/private/tests`. The py4web test task discovers both locations.

The public release mirror excludes private apps as complete directories, so
private-app tests must stay next to the private app rather than in
`py4web/tests`.

## Accessibility Reporting

The separate axe-core task runs advisory checks for WCAG 2.0, 2.1, and 2.2 at levels A and AA. The checked browser
states include the public product and method catalogues, catalogue search and list-view interactions, authentication
forms and validation feedback, and representative pages reached after signing in as a temporary admin.

The report distinguishes between:

- `passes`: rules that passed in a rendered browser state;
- `violations`: automatically established WCAG problems;
- `incomplete`: results that need manual accessibility review.

Violations fail the axe-core task after its report is written. Incomplete results remain advisory because they need
manual accessibility review. A technical error that prevents axe from running also fails the task.

The compact report shows only problems and manual reviews, including the page, browser state, impact, axe rule ID,
exact DOM selector/frame path, short failure explanation, and Deque help URL. The Markdown report is written to:

```text
shared_cache/pytest/axe-report.md
```

`edwh test.run` excludes accessibility scans. Run `edwh test.axe-core` separately; it prints the report inside
`--- START AXE REPORTING ---` and `--- END AXE REPORTING ---` markers for a dedicated CI route and pull-request
comment.

Run the browser suite or the complete test workflow with:

```bash
edwh test.axe-core
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
- the browser task waits for startup after its final restart, then stops all web replicas before merging
  runtime coverage so workers cannot write to the inputs during export
- export/merge runtime data with `edwh test.py4web-runtime-coverage-report`
- this updates `shared_cache/pytest/cov.01_py4web.json` (single py4web report)

The shared coverage exclusions live in `shared_code/coverage.toml`.
They are reused by the containerized suites and the host-side `edwh test.go-tasks` path.

Py4web runtime coverage uses `py4web/coverage.py4web.toml` so web-driven coverage stays scoped to `apps` and `common`, and does not report `shared_code`.

Report-only containers use `--no-deps`. PGQ exports JSON and HTML together; shared-code and runtime
py4web reporting each merge and export in one container. JSON and HTML exports use `--keep-combined`
to preserve their raw inputs, since coverage's export commands can automatically combine and delete
matching input files even after an explicit `coverage combine --keep`.

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
- Database reset behavior: `test.run` temporarily points Compose at a disposable Postgres volume via `POSTGRES_DATA_NAME`, runs `test.go-migrate` inside that throwaway volume, and removes the test database containers and disposable volume afterwards. The normal development Postgres volume remains untouched.
- Stack state after testing: after reporting, `test.run` stops all services in its Compose project, including services in optional profiles. This cleanup also runs when a suite or reporting fails, or the run is interrupted. Use `edwh up` to start the development stack again.
