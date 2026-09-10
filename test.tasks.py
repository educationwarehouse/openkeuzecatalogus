"""Tasks for running containerized test suites and coverage reporting."""

import errno
import fcntl
import importlib.util
import json
import os
import re
import shlex
import shutil
import sys
import typing as t
from contextlib import contextmanager
from copy import copy
from pathlib import Path
from textwrap import dedent

import edwh.tasks
import termcolor._types
from dotenv import load_dotenv
from edwh import DOCKER_COMPOSE
from edwh.tasks import OutputMode
from ewok import Context, Task, task
from invoke import Result
from invoke.exceptions import UnexpectedExit
from tabulate import tabulate
from termcolor import cprint

from tasks import StateOfDevelopment

type AnyDict = dict[str, t.Any]

CACHE_DIR = Path("/shared_cache/pytest")
HOST_CACHE_BASE_DIR = Path("shared_cache")
HOST_CACHE_DIR = HOST_CACHE_BASE_DIR / "pytest"
HOST_SHARED_COVERAGE_CONFIG = "shared_code/coverage.toml"
CONTAINER_SHARED_COVERAGE_CONFIG = "/pythonpath/shared_code/coverage.toml"
CONTAINER_PY4WEB_COVERAGE_CONFIG = "/p4w/coverage.py4web.toml"
CONTAINER_PY4WEB_RUNTIME_COVERAGE_FILE = str(CACHE_DIR / ".coverage.py4web.runtime")
TEST_RUN_LOCK_FILE = HOST_CACHE_BASE_DIR / "pytest.run.lock"
MOCK_INBOX_PATH = HOST_CACHE_BASE_DIR / "mail/mock_inbox.jsonl"
TEST_MIGRATE_SEED_BASE_URL = "file:///data/seeding"

load_dotenv()


def docker_compose(c: Context, args: str) -> Result:
    """Run a docker compose command after enforcing non-production safety."""
    deny_in_productie()
    try:
        return c.run(f"{DOCKER_COMPOSE} {args}", pty=True)
    except UnexpectedExit as err:
        raise RuntimeError(f"docker compose {args} failed") from err


def docker_compose_run(
    c: Context,
    container: str,
    inner_cmd: str,
    environment: AnyDict,
    with_dependencies: bool = True,
) -> Result:
    """Run something in docker compose, with environment variables."""
    environment = copy(environment)
    workdir = environment.pop("WORKDIR", "/pythonpath")
    environment_str = " ".join(f"-e {key}={value}" for key, value in environment.items())
    no_deps_flag = "--no-deps" if not with_dependencies else ""

    # Construct the docker-compose command with COVERAGE_FILE and additional env variables.
    cmd = f"run {no_deps_flag} {environment_str} -w {workdir} --rm {container} {inner_cmd}"
    return docker_compose(c, cmd)


def report_priority(report_path: Path, regex: re.Pattern[str] = re.compile(r"^cov\.(\d+)_")) -> int:
    """Extract numeric merge priority from a coverage report filename."""
    if match := regex.match(report_path.name):
        return int(match.group(1))
    else:
        return 0


class CoverageSummary(t.TypedDict, total=False):
    """Coverage summary fields for a single file entry."""

    covered_lines: int
    num_statements: int
    covered_branches: int
    num_branches: int
    percent_covered: float


class CoverageFileEntry(t.TypedDict, total=False):
    """Single file record in a coverage JSON report."""

    summary: CoverageSummary


class CoverageReport(t.TypedDict, total=False):
    """Top-level structure of a coverage JSON report."""

    files: dict[str, CoverageFileEntry]


def is_productie() -> bool:
    """Return whether the current environment is configured as production."""
    return StateOfDevelopment.from_env().is_productie()


def deny_in_productie() -> None:
    """Abort execution when running with a production state of development."""
    if is_productie():
        raise RuntimeError("test.tasks is blocked for production-level STATE_OF_DEVELOPMENT.")


def in_virtualenv() -> bool:
    """Return whether the current interpreter runs inside a virtual environment."""
    return bool(os.environ.get("VIRTUAL_ENV"))


@task()
def require_virtualenv(_: Context) -> None:
    """Abort early when test.run starts outside an active virtual environment."""
    if not in_virtualenv():
        cprint(
            "test.run must be started from an active virtualenv.",
            "red",
            file=sys.stderr,
        )
        raise SystemExit(1)


def status_color(status: str) -> termcolor._types.Color:
    """Map status values to termcolor color names."""
    options: dict[str, termcolor._types.Color] = {
        "ok": "green",
        "err": "yellow",
        "fatal": "red",
    }

    return options.get(status.split(" ")[0], "grey")


@task()
def go(
    c: Context,
    container: str,
    tests_path: str,
    environment: AnyDict | None = None,
    pytest_args: t.Iterable[str] = (),
) -> Result | None:
    """Run pytest in a specific compose service and test path."""
    # Build -e flags from the environment dict, if any.
    cmd = f"pytest {' '.join(pytest_args)} {tests_path}"
    return docker_compose_run(c, container, cmd, environment=environment or {})


def write_coverage_html(
    c: Context,
    container: str,
    environment: AnyDict,
    coverage_data_file: str,
    suite_name: str,
    rcfile: str = CONTAINER_SHARED_COVERAGE_CONFIG,
) -> None:
    """Generate an HTML coverage report for one suite inside a container."""
    html_cmd = (
        f"coverage html --rcfile={rcfile} -i --data-file={coverage_data_file} -d {CACHE_DIR}/htmlcov/{suite_name}"
    )
    docker_compose_run(c, container=container, inner_cmd=f"sh -lc {shlex.quote(html_cmd)}", environment=environment)


def clear_mock_inbox(c: Context) -> None:
    """Ensure the fake SMTP inbox file starts empty for the next test run."""
    c.run(f"mkdir -p {Path(MOCK_INBOX_PATH).parent} && : > {MOCK_INBOX_PATH}")


def default_pytest_args() -> list[str]:
    """Extra pytest args from env, applied to each pytest-backed `go-*` task."""
    configured = os.getenv("PYTEST_DEFAULT_ARGS", "").strip()
    return shlex.split(configured) if configured else ["-s"]


def resolve_local_pytest_command() -> str | None:
    """Find a usable host-side pytest command for `go_tasks`."""
    venv_pytest = Path(sys.executable).with_name("pytest")
    if venv_pytest.is_file() and os.access(venv_pytest, os.X_OK):
        return shlex.quote(str(venv_pytest))

    pytest_bin = shutil.which("pytest")
    if pytest_bin:
        return shlex.quote(pytest_bin)

    if importlib.util.find_spec("pytest") is not None:
        return f"{shlex.quote(sys.executable)} -m pytest"

    return None


@task(flags={"keyword_search": ("keyword-search", "k")}, iterable=("pytest_args",), pre=[edwh.tasks.setup])
def go_shared_code(
    c: Context,
    pytest_args: t.Iterable[str] = (),
    environment: AnyDict | None = None,
    coverage: bool = True,
    keyword_search: str = "",
) -> Result:
    """Test our abstract backend code in shared code."""
    updated_pytest_args = list(pytest_args) or default_pytest_args()
    if keyword_search:
        updated_pytest_args.extend(("-k", keyword_search))
    environment = copy(environment or default_testing_env())
    environment["WORKDIR"] = "/pythonpath"

    clear_mock_inbox(c)

    if coverage:
        environment["COVERAGE_FILE"] = CACHE_DIR / ".coverage.shared_code"
        updated_pytest_args.extend(coverage_args("shared_code", "01_shared_code"))

    with isolated_test_database(c):
        result = go.body(
            c,
            container="migrate",
            tests_path="shared_code",
            pytest_args=updated_pytest_args,
            environment=environment,
        )
    return result


@task(flags={"keyword_search": ("keyword-search", "k")}, iterable=("pytest_args",), pre=[edwh.tasks.setup])
def go_py4web(
    c: Context,
    pytest_args: t.Iterable[str] = (),
    environment: AnyDict | None = None,
    coverage: bool = True,
    keyword_search: str = "",
) -> Result:
    """Test py4web code in the py4web container."""
    updated_pytest_args = list(pytest_args) or default_pytest_args()
    if keyword_search:
        updated_pytest_args.extend(("-k", keyword_search))
    environment = copy(environment or default_testing_env())
    environment["WORKDIR"] = "/p4w"
    environment["PYTHONPATH"] = "/p4w:/pythonpath"
    environment["SMTP_FAKE"] = "1"

    if coverage:
        environment["COVERAGE_FILE"] = CACHE_DIR / ".coverage.py4web.pytest"
        updated_pytest_args.extend(coverage_args("apps", "01_py4web", CONTAINER_PY4WEB_COVERAGE_CONFIG))
        updated_pytest_args.append("--cov=common")

    with isolated_test_database(c):
        result = go.body(
            c,
            container="py4web",
            tests_path="tests",
            pytest_args=updated_pytest_args,
            environment=environment,
        )
        if coverage:
            write_coverage_html(
                c,
                container="py4web",
                environment=environment,
                coverage_data_file=f"{CACHE_DIR}/.coverage.py4web.pytest",
                suite_name="py4web",
                rcfile=CONTAINER_PY4WEB_COVERAGE_CONFIG,
            )
    return result


@task()
def py4web_runtime_coverage_report(c: Context) -> None:
    """Merge runtime web coverage into the main py4web coverage artifacts."""
    coverage_data_file = f"{CACHE_DIR}/.coverage.py4web"
    runtime_json = f"{CACHE_DIR}/cov.01_py4web.json"

    export_cmd = shlex.quote(
        dedent(
            f"""
            set -euo pipefail
            ls {CACHE_DIR}/.coverage.py4web.runtime* >/dev/null
            inputs="{CACHE_DIR}/.coverage.py4web.runtime*"
            if [ -f "{CACHE_DIR}/.coverage.py4web.pytest" ]; then
              inputs="{CACHE_DIR}/.coverage.py4web.pytest $inputs"
            fi
            coverage combine --keep --data-file={coverage_data_file} $inputs
            coverage json --rcfile={CONTAINER_PY4WEB_COVERAGE_CONFIG} --data-file={coverage_data_file} -o {runtime_json}
            """
        ).strip()
    )
    docker_compose(c, f"exec -T py4web sh -lc {export_cmd}")

    write_coverage_html(
        c,
        container="py4web",
        environment={"WORKDIR": "/p4w"},
        coverage_data_file=coverage_data_file,
        suite_name="py4web",
        rcfile=CONTAINER_PY4WEB_COVERAGE_CONFIG,
    )


def restart_py4web(c: Context) -> None:
    """Restart py4web to pick up env changes and flush runtime coverage data."""
    docker_compose(c, "restart py4web")


def wait_for_py4web(c: Context, attempts: int = 30, sleep_seconds: int = 1) -> None:
    """Wait until py4web is reachable from the playwright network."""
    wait_cmd = dedent(
        f"""
        set -e
        for i in $(seq 1 {attempts}); do
          curl -sf http://py4web:8000/healthcheck >/dev/null && exit 0
          sleep {sleep_seconds}
        done
        echo 'py4web not reachable from playwright container' >&2
        exit 1
        """
    ).strip()
    docker_compose(c, f"run --rm --no-deps playwright sh -lc {shlex.quote(wait_cmd)}")


def recreate_py4web(c: Context, runtime_coverage: bool = True) -> None:
    """Recreate py4web with optional runtime coverage env for browser-driven tests."""
    cmd = f"{DOCKER_COMPOSE} up -d --force-recreate py4web"
    compose_env = default_testing_env()
    if runtime_coverage:
        compose_env["PY4WEB_COVERAGE_PROCESS_START"] = CONTAINER_PY4WEB_COVERAGE_CONFIG
        compose_env["PY4WEB_COVERAGE_FILE"] = CONTAINER_PY4WEB_RUNTIME_COVERAGE_FILE
    c.run(
        cmd,
        pty=True,
        env=compose_env,
    )


@task(flags={"keyword_search": ("keyword-search", "k")}, iterable=("pytest_args",), pre=[edwh.tasks.setup])
def go_web(
    c: Context,
    pytest_args: t.Iterable[str] = (),
    environment: AnyDict | None = None,
    coverage: bool = True,
    keyword_search: str = "",
) -> Result | None:
    """Run browser-driven Playwright tests against the running py4web service."""
    migration_environment = default_testing_env() | {"MIGRATE_SEED_CATALOG_CONFIGURATION": "1"}
    if os.environ.get("TEST_DATABASE_ISOLATED") == "1":
        go_migrate(c, coverage=False, environment=migration_environment)

    with isolated_test_database(c, migration_environment=migration_environment):
        recreate_py4web(c, runtime_coverage=coverage)

        if coverage:
            restart_py4web(c)
            docker_compose(c, "up -d pgq-applog")
            edwh.tasks.wait_until_healthy(c, ["py4web", "pgq-applog"])

            try:
                bash_check_coverage_used = shlex.quote(
                    f'[ "${{COVERAGE_PROCESS_START:-}}" = "{CONTAINER_PY4WEB_COVERAGE_CONFIG}" ]'
                    f' && [ "${{COVERAGE_FILE:-}}" = "{CONTAINER_PY4WEB_RUNTIME_COVERAGE_FILE}" ]'
                )
                docker_compose(c, f"exec -T py4web sh -lc {bash_check_coverage_used}")
            except UnexpectedExit as e:
                raise RuntimeError(
                    "PY4WEB runtime coverage is disabled (COVERAGE_PROCESS_START or COVERAGE_FILE mismatch)."
                ) from e

        wait_for_py4web(c)
        clear_mock_inbox(c)

        updated_pytest_args = list(pytest_args) or default_pytest_args()
        if keyword_search:
            updated_pytest_args.extend(("-k", keyword_search))
        environment = copy(environment or default_testing_env())
        environment["WORKDIR"] = "/work"

        environment.setdefault("WEB_BASE_URL", "http://py4web:8000")
        result = docker_compose_run(
            c,
            container="playwright",
            inner_cmd=f"pytest {' '.join(updated_pytest_args)} tests",
            environment=environment,
            with_dependencies=False,
        )

        if coverage:
            flush_cmd = dedent(
                """
                resp="$(curl -fsS http://py4web:8000/_flush-runtime-coverage)"
                [ "$resp" = "flushed" ] || { echo "unexpected flush response: $resp" >&2; exit 1; }
                """
            ).strip()
            docker_compose_run(
                c,
                container="playwright",
                inner_cmd=f"sh -lc {shlex.quote(flush_cmd)}",
                environment={"WORKDIR": "/work"},
                with_dependencies=False,
            )
            restart_py4web(c)
            py4web_runtime_coverage_report(c)

    return result


@task(flags={"keyword_search": ("keyword-search", "k")}, iterable=("pytest_args",), pre=[edwh.tasks.setup])
def go_pgq(
    c: Context,
    pytest_args: t.Iterable[str] = (),
    environment: AnyDict | None = None,
    coverage: bool = True,
    keyword_search: str = "",
) -> Result:
    """Test pgq code in the pgq container."""
    updated_pytest_args = list(pytest_args) or default_pytest_args()
    if keyword_search:
        updated_pytest_args.extend(("-k", keyword_search))
    environment = copy(environment or default_testing_env())
    environment["WORKDIR"] = "/pythonpath"

    if coverage:
        environment["COVERAGE_FILE"] = CACHE_DIR / ".coverage.pgq"
        updated_pytest_args.extend(coverage_args("pgq", "01_pgq"))
        updated_pytest_args.extend(
            [
                "--cov=shared_code/modules/scrapers",
                "--cov=shared_code/infra/http",
            ]
        )

    with isolated_test_database(c):
        result = go.body(
            c,
            container="pgq-applog",
            tests_path="pgq",
            pytest_args=updated_pytest_args,
            environment=environment,
        )
        if coverage:
            write_coverage_html(
                c,
                container="pgq-applog",
                environment=environment,
                coverage_data_file=f"{CACHE_DIR}/.coverage.pgq",
                suite_name="pgq",
            )
    return result


@task(flags={"keyword_search": ("keyword-search", "k")}, iterable=("pytest_args",), pre=[edwh.tasks.setup])
def go_tasks(
    c: Context,
    pytest_args: t.Iterable[str] = (),
    _environment: AnyDict | None = None,
    _coverage: bool = True,
    keyword_search: str = "",
) -> Result | None:
    """Test invoke task definitions locally (outside docker)."""
    pytest_cmd = resolve_local_pytest_command()
    if pytest_cmd is None:
        cprint(
            "No usable pytest was found. Activate the virtualenv or install pytest before running this task.",
            "red",
            file=sys.stderr,
        )
        return None

    coverage = False
    # todo: do we need to test more of tasks.py?
    #  Since that's mostly dev-ops and not actual implementation code

    project_root = Path(__file__).resolve().parent
    host_cache = (project_root / HOST_CACHE_DIR).resolve()
    host_cache.mkdir(parents=True, exist_ok=True)

    updated_pytest_args = [
        arg for arg in (list(pytest_args) or default_pytest_args()) if not arg.startswith("-o cache_dir=")
    ]
    updated_pytest_args.append(f"-o cache_dir={host_cache}")
    if keyword_search:
        updated_pytest_args.extend(("-k", keyword_search))

    coverage_file = host_cache / ".coverage.tasks"
    if coverage:
        updated_pytest_args.extend(
            [
                "--cov=tasks",
                "--cov-branch",
                f"--cov-config={HOST_SHARED_COVERAGE_CONFIG}",
                "--cov-report=",
                f"--cov-report=json:{host_cache}/cov.01_tasks.json",
            ]
        )

    tests_path = (project_root / "tests").resolve()
    cmd = f"{pytest_cmd} {' '.join(updated_pytest_args)} {shlex.quote(str(tests_path))}"
    run_env = copy(default_testing_env())
    if coverage:
        run_env["COVERAGE_FILE"] = str(coverage_file)

    result = c.run(cmd, env=run_env, pty=True)

    if coverage:
        c.run(
            (
                f"coverage html --rcfile={HOST_SHARED_COVERAGE_CONFIG} -i "
                f"--data-file={coverage_file} -d {host_cache}/htmlcov/tasks"
            ),
            env=run_env,
            pty=True,
        )

    return result


@task(flags={"keyword_search": ("keyword-search", "k")}, pre=[edwh.tasks.setup])
def go_migrate(
    c: Context,
    _pytest_args: t.Iterable[str] = (),
    environment: AnyDict | None = None,
    coverage: bool = True,
    keyword_search: str = "",
) -> Result | None:
    """Reset database, run migrations, and collect migration-run coverage."""
    environment = default_testing_env() | copy(environment or {})
    environment["WORKDIR"] = "/pythonpath"
    if coverage:
        environment["COVERAGE_FILE"] = CACHE_DIR / ".coverage.migrate"

    c.run("rm -f migrate/flags/migrate-*.complete", pty=True)

    docker_compose(c, "rm -fsv pg-0")
    if os.environ.get("TEST_DATABASE_ISOLATED") == "1" and (volume_name := os.environ.get("POSTGRES_DATA_NAME")):
        c.run(f"docker volume rm -f {shlex.quote(volume_name)}", pty=True)

    docker_compose(c, "up -d pg-0 redis-master")

    wait_for_pg_cmd = (
        "until pg_isready --dbname=$POSTGRES_DATABASE --username=$POSTGRES_USERNAME -h pg-0; do sleep 1; done"
    )
    docker_compose(c, f"run --rm pg-0 sh -lc {shlex.quote(wait_for_pg_cmd)}")

    migrate_report = f"{CACHE_DIR}/cov.02_migrate.json"
    migrate_cmd = "/opt/venv/bin/migrate"
    if coverage:
        migrate_cmd = (
            f"coverage run --rcfile={CONTAINER_SHARED_COVERAGE_CONFIG} --branch /opt/venv/bin/migrate && "
            f"coverage json --rcfile={CONTAINER_SHARED_COVERAGE_CONFIG} "
            f"--include='/pythonpath/shared_code/migrations/*' -o {migrate_report}"
        )

    result = docker_compose_run(
        c, container="migrate", inner_cmd=f"sh -lc {shlex.quote(migrate_cmd)}", environment=environment
    )

    # No dedicated migrate HTML report: migration coverage is folded into shared_code HTML.
    return result


def coverage_args(
    cov_target: str,
    suite_name: str,
    cov_config: str = CONTAINER_SHARED_COVERAGE_CONFIG,
) -> list[str]:
    """Coverage arguments for a single source root."""
    return [
        f"--cov={cov_target}",
        "--cov-branch",
        f"--cov-config={cov_config}",
        "--cov-report=",
        f"--cov-report=json:{CACHE_DIR}/cov.{suite_name}.json",
    ]


@contextmanager
def restore_database_after_tests(c: Context) -> t.Iterator[None]:
    """Run tests against a disposable postgres volume and remove it afterwards."""
    volume_name = f"{os.environ['PROJECT']}_postgres_data_test_run"
    os.environ["POSTGRES_DATA_NAME"] = volume_name
    try:
        yield
    finally:
        docker_compose(c, "rm -fsv pg-0")
        c.run(f"docker volume rm -f {shlex.quote(volume_name)}", pty=True)
        os.environ.pop("POSTGRES_DATA_NAME", None)


@contextmanager
def isolated_test_database(c: Context, migration_environment: AnyDict | None = None) -> t.Iterator[None]:
    """Provide a migrated disposable test database unless one is already active."""
    if os.environ.get("TEST_DATABASE_ISOLATED") == "1":
        yield
        return

    os.environ["TEST_DATABASE_ISOLATED"] = "1"
    try:
        with restore_database_after_tests(c):
            go_migrate(c, coverage=False, environment=migration_environment)
            yield
    finally:
        os.environ.pop("TEST_DATABASE_ISOLATED", None)


@contextmanager
def lock_test_run(lock_file: Path = TEST_RUN_LOCK_FILE, wait: bool = True, verbose: bool = False) -> t.Iterator[bool]:
    """Ensure only one test.run process executes at a time."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("w") as lock_handle:
        lock_mode = fcntl.LOCK_EX if wait else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        if verbose and wait:
            print("[lock] waiting for lock...")
        try:
            fcntl.flock(lock_handle.fileno(), lock_mode)
            if verbose:
                print("[lock] acquired lock")
        except OSError as err:
            if not wait and err.errno in (errno.EACCES, errno.EAGAIN):
                yield False
                return
            raise err
        try:
            yield True
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def default_testing_env() -> dict[str, t.Any]:
    """Return baseline environment variables for test commands."""
    return {
        "STATE_OF_DEVELOPMENT": "test",
        "PYTHONWARNINGS": "ignore::SyntaxWarning",
        "MIGRATE_SEED_BASE_URL": TEST_MIGRATE_SEED_BASE_URL,
        "SMTP_FAKE": "1",
        "IMAGE_STORAGE_FAKE": "1",
        "APPLOG_FAKE": "1",
        "ERROR_SIGNAL_BACKEND": "mock",
        "ENTREE_FAKE": "1",
        "ENTREE_CLIENT_ENDPOINT": "http://py4web:8000/auth/entree_mock_authorize",
        "PYTEST_MOCK_EMAIL_DOMAIN": "pytest-mock.local",
    }


def _build_full_suite_pytest_options(
    show_output: bool = False,
    verbose: bool = False,
    exitfirst: bool = False,
    keyword_search: str = "",
    extra: str = "",
) -> list[str]:
    pytest_options = [f"-o cache_dir={CACHE_DIR}"]

    if extra:
        pytest_options.append(extra)
    if show_output:
        pytest_options.append("-s")
    if verbose:
        pytest_options.append("-v")
    if exitfirst:
        pytest_options.append("-x")
    if keyword_search:
        pytest_options.append(f"-k {keyword_search}")

    if len(pytest_options) == 1:
        pytest_options.extend(default_pytest_args())

    return pytest_options


def _collect_full_suite_tasks(apps: set[str]) -> dict[str, Task]:
    tests = {
        "tasks": go_tasks,
        "migrate": go_migrate,
        "pgq": go_pgq,
        "shared-code": go_shared_code,
        "py4web": go_py4web,
        "web": go_web,
    }

    # filter specific ones
    return {k: v for k, v in tests.items() if k in apps} if apps else tests


@task()
def collect_shared_code_coverage(c: Context, environment: AnyDict, container: str = "pgq-applog") -> None:
    """Combine all suite coverage files and generate the shared_code JSON + HTML report.

    Runs in pgq-applog so all source files (pgq + shared_code) are present.
    """
    # uses pgq- container because that has access to both shared code (used by importer) and pgq paths
    collect_cmd = dedent(
        f"""
        inputs=""
        for f in "{CACHE_DIR}/.coverage.shared_code" "{CACHE_DIR}/.coverage.migrate" "{CACHE_DIR}/.coverage.pgq"; do
            [ -f "$f" ] && inputs="$inputs $f"
        done
        coverage combine --keep --data-file={CACHE_DIR}/.coverage.shared_code.merged $inputs
        coverage json \
            --rcfile={CONTAINER_SHARED_COVERAGE_CONFIG} \
            --data-file={CACHE_DIR}/.coverage.shared_code.merged \
            -o {CACHE_DIR}/cov.01_shared_code.json
        """
    ).strip()
    env = environment | {"WORKDIR": "/pythonpath"}
    docker_compose_run(c, container=container, inner_cmd=f"sh -lc {shlex.quote(collect_cmd)}", environment=env)
    write_coverage_html(
        c,
        container=container,
        environment=env,
        coverage_data_file=f"{CACHE_DIR}/.coverage.shared_code.merged",
        suite_name="shared_code",
    )


def run_suite_task(
    c: Context,
    test: Task,
    pytest_options: list[str],
    environment: dict,
    coverage: bool,
) -> str:
    """Execute a test suite task and handle its result."""
    try:
        edwh.tasks.set_permissions(
            c,
            "shared_cache",
            filepermissions=666,
            directorypermissions=777,
        )

        result = test.body(c, copy(pytest_options), copy(environment), coverage)

        is_ok = result.ok if isinstance(result, Result) else bool(result)

        return "ok" if is_ok else "err"

    except Exception as e:
        return f"fatal {e}"


def run_full_suite(
    c: Context,
    show_output: bool = False,
    verbose: bool = False,
    exitfirst: bool = False,
    keyword_search: str = "",
    coverage: bool = True,
    extra: str = "",
    apps: t.Iterable[str] | None = None,
    mode: OutputMode = "cli",
) -> None:
    """Once `run` acquires a lock to ensure only one test suite runs at a time, run each test and aggregate results."""
    c.sudo(f"rm -rf {HOST_CACHE_DIR}")

    pytest_options = _build_full_suite_pytest_options(
        show_output=show_output,
        verbose=verbose,
        exitfirst=exitfirst,
        keyword_search=keyword_search,
        extra=extra,
    )

    environment = default_testing_env()

    if coverage:
        environment["COVERAGE_FILE"] = CACHE_DIR / ".coverage"

    tests = _collect_full_suite_tasks(set(apps or ()))

    results: dict[str, str] = {}

    with isolated_test_database(c):
        for test_name, test in tests.items():
            results[test_name] = run_suite_task(
                c,
                test,
                pytest_options=pytest_options,
                environment=environment,
                coverage=coverage,
            )

            if exitfirst and results[test_name] != "ok":
                break

    all_ok = all(value == "ok" for value in results.values())

    if coverage:
        collect_shared_code_coverage(c, environment)

    print("--- START REPORTING ---")

    if coverage and all_ok and not report(c):
        # report prints and returns boolean for threshold ok
        all_ok = False

    if mode == "json":
        print(json.dumps(results))
    else:
        for test_name, status in results.items():
            edwh.tasks._print_lint_status(f"{test_name}: {status}", ok=status == "ok", output=mode)

    print("--- END REPORTING ---")

    if not all_ok:
        exit(1)
    # else: exit ok


@task(
    flags={
        "exitfirst": ("exitfirst", "x"),
        "no_wait_for_lock": ("no-wait-for-lock",),
    },
    iterable=("apps",),
    pre=[require_virtualenv, edwh.tasks.setup, edwh.tasks.stop],
)
def run(
    c: Context,
    show_output: bool = False,  # -s
    verbose: bool = False,  # -v
    exitfirst: bool = False,  # -x
    no_wait_for_lock: bool = False,
    keyword_search: str = "",  # -k
    apps: t.Iterable[str] | None = None,  # -a x -a y
    coverage: bool = True,
    extra: str = "",
    output: OutputMode = "cli",
) -> None:
    """Main entrypoint that runs the full test suite (if not in production mode)."""
    deny_in_productie()

    with lock_test_run(wait=not no_wait_for_lock, verbose=verbose) as got_lock:
        if not got_lock:
            cprint(f"test.run is already active (lock: {TEST_RUN_LOCK_FILE})", "yellow")
            raise SystemExit(1)

        return run_full_suite(
            c,
            show_output=show_output,
            verbose=verbose,
            exitfirst=exitfirst,
            keyword_search=keyword_search,
            coverage=coverage,
            extra=extra,
            apps=apps or None,
            mode=output,
        )


class CoverageRow(t.TypedDict):
    """Merged coverage metrics for one file."""

    statements: int
    covered_lines: int
    branches: int
    covered_branches: int
    percent_covered: float
    priority: int


type CoveragePerFile = dict[str, CoverageRow]


def merge_coverage_files() -> CoveragePerFile:
    """Merge suite coverage JSON files, preferring entries with higher priority."""
    cache_dir = HOST_CACHE_DIR
    if not cache_dir.exists():
        cache_dir = CACHE_DIR

    suite_reports = sorted(cache_dir.glob("cov.*.json"))
    if not suite_reports:
        raise FileNotFoundError(f"No coverage json files found in {cache_dir}")

    file_rows: CoveragePerFile = {}
    for report_path in suite_reports:
        data: CoverageReport = json.loads(report_path.read_text())
        priority = report_priority(report_path)
        for filename, entry in data.get("files", {}).items():
            summary = entry.get("summary", {})
            statements = int(summary.get("num_statements", 0))
            covered_lines = int(summary.get("covered_lines", 0))
            branches = int(summary.get("num_branches", 0))
            covered_branches = int(summary.get("covered_branches", 0))
            percent_covered = float(summary.get("percent_covered", 0.0))
            prev_priority = file_rows.get(filename, {}).get("priority", -1)
            if priority >= prev_priority:
                file_rows[filename] = CoverageRow(
                    statements=statements,
                    covered_lines=covered_lines,
                    branches=branches,
                    covered_branches=covered_branches,
                    percent_covered=percent_covered,
                    priority=priority,
                )

    return file_rows


@task()
def report_html(c: Context) -> None:
    """Build per-suite HTML coverage reports and a simple index page."""
    html_index_dir = HOST_CACHE_DIR / "htmlcov"

    edwh.tasks.set_permissions(c, str(html_index_dir))

    html_index_dir.mkdir(parents=True, exist_ok=True)
    suite_dirs = sorted(
        path.name for path in html_index_dir.iterdir() if path.is_dir() and (path / "index.html").exists()
    )
    links = "\n".join(f"<li><a href='{suite}/index.html'>{suite}</a></li>" for suite in suite_dirs)
    (html_index_dir / "index.html").write_text(
        f"""<!doctype html>
                <html>
                <head><meta charset='utf-8'><title>Coverage Reports</title></head>
                <body>
                <h1>Coverage Reports</h1>
                <ul>
                {links}
                </ul>
                </body>
                </html>
                """,
        encoding="utf-8",
    )
    print(f"HTML coverage index written to {HOST_CACHE_DIR}/htmlcov/index.html")


@task()
def report(c: Context, min_coverage: float = 80.0) -> bool:
    """Report aggregate coverage from per-suite JSON reports."""
    file_rows = merge_coverage_files()

    total_statements = sum(row["statements"] for row in file_rows.values())
    total_covered_lines = sum(row["covered_lines"] for row in file_rows.values())
    total_branches = sum(row["branches"] for row in file_rows.values())
    total_covered_branches = sum(row["covered_branches"] for row in file_rows.values())

    # Per-file "Cover" uses coverage's own `percent_covered`; combined is a weighted aggregate across merged rows.
    total_items = total_statements + total_branches
    total_covered_items = total_covered_lines + total_covered_branches
    total_percent = (100.0 * total_covered_items / total_items) if total_items else 100.0

    # Fixed output schema for tabular rendering, so a short tuple is fine here.
    rows: list[tuple[str, int, int, str]] = []
    for filename in sorted(file_rows):
        row = file_rows[filename]
        total_file_items = row["statements"] + row["branches"]
        total_file_covered = row["covered_lines"] + row["covered_branches"]
        missing = total_file_items - total_file_covered
        rows.append((filename[:60], total_file_items, missing, f"{row['percent_covered']:.2f}%"))
    rows.append(("combined", total_items, total_items - total_covered_items, f"{total_percent:.2f}%"))
    print(tabulate(rows, headers=("Name", "Items", "Miss", "Cover")))

    report_html(c)

    if total_percent < min_coverage:
        cprint(f"Coverage threshold not met: {total_percent:.2f}% < {min_coverage:.2f}%", color="red")
        return False
    else:
        cprint(f"Coverage threshold met: {total_percent:.2f}% >= {min_coverage:.2f}%", color="green")
        return True


@task()
def htmlcov(c: Context) -> None:
    """Open the htmlcov directory in your prefered browser."""
    c.run("xdg-open shared_cache/pytest/htmlcov/index.html")
