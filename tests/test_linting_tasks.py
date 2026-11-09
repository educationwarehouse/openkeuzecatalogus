"""Regression tests for project-specific EW lint rules."""

import ast
import importlib.util
import sys
from pathlib import Path
from textwrap import dedent

LINTING_TASKS_PATH = Path(__file__).parents[1] / "linting.tasks.py"
LINTING_TASKS_SPEC = importlib.util.spec_from_file_location("linting_tasks", LINTING_TASKS_PATH)
assert LINTING_TASKS_SPEC is not None
assert LINTING_TASKS_SPEC.loader is not None
linting_tasks = importlib.util.module_from_spec(LINTING_TASKS_SPEC)
sys.modules[LINTING_TASKS_SPEC.name] = linting_tasks
LINTING_TASKS_SPEC.loader.exec_module(linting_tasks)


def make_module(name: str, source: str) -> object:
    """Build a source module for a lint fixture."""
    source = dedent(source).lstrip()
    path = Path(*name.split(".")).with_suffix(".py")
    tree = ast.parse(source, filename=str(path))
    return linting_tasks.SourceModule(
        path=path,
        name=name,
        tree=tree,
        source=source,
        imports=linting_tasks.import_bindings(tree, name, False),
    )


def test_ew001_reports_monkeypatch_setattr_and_honors_noqa() -> None:
    """Report unsuppressed monkeypatch.setattr calls while honoring noqa."""
    module = make_module(
        "example.test_rule",
        """
        monkeypatch.setattr(target, "name", value)
        monkeypatch.setattr(target, "name", value)  # noqa: EW001
        other.setattr(target, "name", value)
        """,
    )

    violations = linting_tasks.check_monkeypatch_setattr(
        module.path,
        module.tree,
        "EW001",
        "avoid monkeypatch.setattr",
    )
    unsuppressed = [
        violation for violation in violations if not linting_tasks.is_suppressed(module.source.splitlines(), violation)
    ]

    assert [(violation.line, violation.column, violation.code) for violation in unsuppressed] == [(1, 1, "EW001")]


def test_ew002_allows_from_env_inside_factory_only() -> None:
    """Allow from_env calls inside factories and report calls outside them."""
    module = make_module(
        "example.services",
        """
        from endow import Injectable

        class Service(Injectable):
            @classmethod
            def from_env(cls):
                return cls.from_env()

        Service.from_env()
        """,
    )

    violations = linting_tasks.check_endow_from_env({module.name: module}, "EW002", "use with_injected")

    assert [(violation.line, violation.column, violation.code) for violation in violations] == [(8, 1, "EW002")]


def test_ew003_reports_missing_endow_runtime_input() -> None:
    """Report missing runtime inputs for injected dependencies."""
    module = make_module(
        "example.services",
        """
        from endow import Injectable

        class Database(Injectable):
            @classmethod
            def from_env(cls, dsn: str):
                return cls()

        class Service(Injectable):
            database: Database

        Service.with_injected()
        Service.with_injected(dsn="postgresql://example.test")
        """,
    )

    violations = linting_tasks.check_endow_runtime_inputs({module.name: module}, "EW003", "provide runtime inputs")

    assert [(violation.line, violation.column, violation.code) for violation in violations] == [(11, 1, "EW003")]
    assert "dsn via Service.database -> Database.from_env(dsn)" in violations[0].message


def test_ew004_reports_a_defaulted_argument_immediately_after_a_bare_star() -> None:
    """Report defaulted arguments that immediately follow a bare star."""
    module = make_module(
        "example.signatures",
        """
        def sync(*, enabled: bool = False, limit: int = 10):
            pass

        async def asynchronous(*, name: str = "default"):
            pass

        def allowed(*values: str, enabled: bool = False):
            pass

        def required_first(*, email: str, expected_redirect_path: str | None = None):
            pass
        """,
    )

    violations = linting_tasks.check_bare_star_default_arguments(
        module.path,
        module.tree,
        "EW004",
        "do not use a bare * before a defaulted parameter",
    )

    assert [(violation.line, violation.code) for violation in violations] == [
        (1, "EW004"),
        (4, "EW004"),
    ]


def test_ew005_reports_project_defaulted_parameters_passed_positionally() -> None:
    """Report positional calls that pass project defaulted parameters."""
    helpers = make_module(
        "example.helpers",
        """
        def imported(required: str, option: str = "default") -> None:
            pass

        class Builder:
            def __init__(self, required: str, option: str = "default") -> None:
                pass
        """,
    )
    caller = make_module(
        "example.caller",
        """
        from example.helpers import Builder, imported as imported_alias
        import example.helpers as helpers

        def local(required: str, option: str = "default") -> None:
            pass

        def caller() -> None:
            local("required", "positional")
            imported_alias("required", "positional")
            helpers.imported("required", "positional")
            Builder("required", "positional")
            local("required", option="keyword")
            unknown("required", "positional")
            local(*values)

        class Local:
            def method(self, required: str, option: str = "default") -> None:
                pass

            def caller(self) -> None:
                self.method("required", "positional")
        """,
    )

    violations = linting_tasks.check_default_arguments_passed_positionally(
        {helpers.name: helpers, caller.name: caller},
        "EW005",
        "pass defaulted parameters by keyword",
    )

    assert [(violation.path, violation.line, violation.code) for violation in violations] == [
        (caller.path, 8, "EW005"),
        (caller.path, 9, "EW005"),
        (caller.path, 10, "EW005"),
        (caller.path, 11, "EW005"),
        (caller.path, 21, "EW005"),
    ]


def test_ew005_allows_defaulted_positional_parameters_on_noqa_declarations() -> None:
    """Allow callables to opt out of EW005 from their declaration."""
    module = make_module(
        "example.decorators",
        """
        def template(  # noqa: EW005
            name: str | None = None,
        ) -> None:
            pass

        def caller() -> None:
            template("index.html")
        """,
    )

    violations = linting_tasks.check_default_arguments_passed_positionally(
        {module.name: module},
        "EW005",
        "pass defaulted parameters by keyword",
    )

    assert violations == []
