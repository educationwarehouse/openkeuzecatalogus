"""Project-specific lint tasks."""

import ast
import dataclasses
import re
import typing as t
from pathlib import Path

from ewok import Context, task

NOQA_PATTERN = re.compile(r"#\s*noqa:\s*(?P<codes>.*)", re.IGNORECASE)
NOQA_CODE_PATTERN = re.compile(r"\b[A-Z]+[0-9]+\b")


@dataclasses.dataclass(frozen=True)
class CustomLintViolation:
    """A single violation from a project-specific lint rule."""

    path: Path
    line: int
    column: int
    code: str
    message: str

    def format(self) -> str:
        """Render in the same location-first style as Ruff."""
        return f"{self.path}:{self.line}:{self.column}: {self.code} {self.message}"


class CustomLintChecker(t.Protocol):
    """Callable contract for a project-specific lint rule."""

    def __call__(self, path: Path, tree: ast.AST, code: str, message: str) -> t.Sequence[CustomLintViolation]:
        """Return violations for a parsed Python module."""


@dataclasses.dataclass(frozen=True)
class CustomLintRule:
    """Project-specific lint rule definition."""

    code: str
    message: str
    checker: CustomLintChecker


def check_monkeypatch_setattr(path: Path, tree: ast.AST, code: str, message: str) -> t.Sequence[CustomLintViolation]:
    """Find `monkeypatch.setattr(...)` calls."""
    violations: list[CustomLintViolation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "setattr":
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id != "monkeypatch":
            continue

        violations.append(
            CustomLintViolation(
                path=path,
                line=node.lineno,
                column=node.col_offset + 1,
                code=code,
                message=message,
            )
        )

    return violations


CUSTOM_LINT_RULES: tuple[CustomLintRule, ...] = (
    CustomLintRule(
        code="EW001",
        message="avoid monkeypatch.setattr; use a focused fixture or explicit test seam instead",
        checker=check_monkeypatch_setattr,
    ),
)


def discover_python_files(ctx: Context) -> list[Path]:
    """Discover Python files using ripgrep's ignore-aware file listing."""
    result = ctx.run("rg --files -g '*.py'", hide=True)
    return [Path(line) for line in result.stdout.splitlines()]


def noqa_codes(line: str) -> set[str]:
    """Return noqa codes from a source line."""
    match = NOQA_PATTERN.search(line)
    if not match:
        return set()

    codes = match.group("codes").strip()
    if not codes:
        return {"ALL"}

    return set(NOQA_CODE_PATTERN.findall(codes))


def is_suppressed(lines: t.Sequence[str], violation: CustomLintViolation) -> bool:
    """Check whether a violation is suppressed by a same-line noqa."""
    if violation.line < 1 or violation.line > len(lines):
        return False

    codes = noqa_codes(lines[violation.line - 1])
    return "ALL" in codes or violation.code in codes


def custom_lint_violations(ctx: Context) -> list[CustomLintViolation]:
    """Run all custom lint rules and return unsuppressed violations."""
    violations: list[CustomLintViolation] = []

    for path in discover_python_files(ctx):
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()

        for rule in CUSTOM_LINT_RULES:
            for violation in rule.checker(path, tree, rule.code, rule.message):
                if not is_suppressed(lines, violation):
                    violations.append(violation)

    return violations


@task()
def custom(ctx: Context) -> bool:
    """Run project-specific EW lint rules."""
    violations = custom_lint_violations(ctx)

    for violation in violations:
        print(violation.format())

    # 1 if violations else 0
    raise SystemExit(int(bool(violations)))
