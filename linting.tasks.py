"""Project-specific lint tasks."""

import ast
import dataclasses
import importlib
import re
import typing as t
from pathlib import Path

from endow import Injectable
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
    checker: CustomLintChecker | None = None
    project_checker: t.Callable[..., t.Sequence[CustomLintViolation]] | None = None


@dataclasses.dataclass(frozen=True)
class SourceModule:
    """Parsed Python source and the names it imports."""

    path: Path
    name: str
    tree: ast.Module
    source: str
    imports: dict[str, str]


@dataclasses.dataclass(frozen=True)
class SourceClass:
    """A class declaration available to static Endow graph inspection."""

    key: str
    module: SourceModule
    node: ast.ClassDef


def is_endow_injectable(reference: str) -> bool:
    """Return whether an Endow symbol is an `Injectable` subclass."""
    if not reference.startswith("endow."):
        return False

    module_name, _, name = reference.rpartition(".")
    candidate = getattr(importlib.import_module(module_name), name, None)
    return isinstance(candidate, type) and issubclass(candidate, Injectable)


class EndowCallLinter(ast.NodeVisitor):
    """Check Endow construction calls against the source-defined dependency graph."""

    def __init__(self, modules: dict[str, SourceModule], codes: set[str]) -> None:
        """Store the parsed source modules and index their class declarations."""
        self.modules = modules
        self.codes = codes
        self.classes = self._discover_classes()
        self.function_names: list[str] = []
        self.violations: list[CustomLintViolation] = []

    def _discover_classes(self) -> dict[str, SourceClass]:
        classes: dict[str, SourceClass] = {}
        for module in self.modules.values():
            for node in module.tree.body:
                if isinstance(node, ast.ClassDef):
                    classes[f"{module.name}.{node.name}"] = SourceClass(
                        key=f"{module.name}.{node.name}", module=module, node=node
                    )
        return classes

    def lint(self) -> list[CustomLintViolation]:
        """Return violations for every Endow construction call in the indexed source."""
        for module in self.modules.values():
            self.module = module
            self.function_names = []
            self.visit(module.tree)
        return self.violations

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track the enclosing function while inspecting calls."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track the enclosing async function while inspecting calls."""
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visit a function while recording its name as lexical context."""
        self.function_names.append(node.name)
        self.generic_visit(node)
        self.function_names.pop()

    def visit_Call(self, node: ast.Call) -> None:
        """Check Endow `from_env` and `with_injected` calls."""
        if isinstance(node.func, ast.Attribute):
            class_key = self._resolve_expression(node.func.value, self.module)
            if class_key and self._is_injectable(class_key):
                if node.func.attr == "from_env" and "EW002" in self.codes and "from_env" not in self.function_names:
                    self._violate(node, "EW002", "call .with_injected(...) instead of direct Endow .from_env(...)")
                if node.func.attr == "with_injected" and "EW003" in self.codes:
                    self._check_runtime_inputs(node, class_key)
        self.generic_visit(node)

    def _check_runtime_inputs(self, node: ast.Call, class_key: str) -> None:
        provided = {keyword.arg for keyword in node.keywords if keyword.arg is not None}
        requirements = self._runtime_requirements(class_key, provided)
        missing = [requirement for requirement in requirements if requirement[0] not in provided]
        if not missing:
            return
        details = ", ".join(f"{name} via {' -> '.join(path)}" for name, path in missing)
        self._violate(node, "EW003", f"missing Endow runtime input(s): {details}")

    def _runtime_requirements(self, class_key: str, provided: set[str]) -> list[tuple[str, tuple[str, ...]]]:
        return RuntimeRequirementCollector(self, provided).collect(class_key)

    def _fields(self, source_class: SourceClass) -> dict[str, tuple[SourceModule, ast.expr]]:
        fields: dict[str, tuple[SourceModule, ast.expr]] = {}
        for base_key in self._bases(source_class):
            if base_key in self.classes and self._is_injectable(base_key):
                fields.update(self._fields(self.classes[base_key]))
        for node in source_class.node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                fields[node.target.id] = (source_class.module, node.annotation)
        return {name: annotation for name, annotation in fields.items() if not name.startswith("_")}

    def _factory(self, source_class: SourceClass) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in source_class.node.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "from_env":
                return node
        for base_key in self._bases(source_class):
            if base_key in self.classes:
                factory = self._factory(self.classes[base_key])
                if factory:
                    return factory
        return None

    @staticmethod
    def _required_factory_arguments(factory: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
        positional = (*factory.args.posonlyargs, *factory.args.args)
        positional = positional[1:] if positional else ()
        defaults = len(factory.args.defaults)
        required_positional = positional[:-defaults] if defaults else positional
        required_keyword = tuple(
            argument.arg
            for argument, default in zip(factory.args.kwonlyargs, factory.args.kw_defaults, strict=True)
            if default is None
        )
        return tuple(argument.arg for argument in required_positional) + required_keyword

    def _bases(self, source_class: SourceClass) -> tuple[str, ...]:
        return tuple(
            resolved
            for base in source_class.node.bases
            if (resolved := self._resolve_expression(base, source_class.module)) is not None
        )

    def _is_injectable(self, class_key: str, seen: set[str] | None = None) -> bool:
        if is_endow_injectable(class_key):
            return True
        if class_key not in self.classes:
            return False
        seen = seen or set()
        if class_key in seen:
            return False
        return any(self._is_injectable(base, seen | {class_key}) for base in self._bases(self.classes[class_key]))

    def _resolve_expression(self, expression: ast.expr, module: SourceModule) -> str | None:
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            try:
                forward_reference = ast.parse(expression.value, mode="eval").body
            except SyntaxError:
                return None
            return self._resolve_expression(forward_reference, module)
        if isinstance(expression, ast.Name):
            return self._resolve_name(expression.id, module)
        if isinstance(expression, ast.Attribute):
            base = self._resolve_expression(expression.value, module)
            return self._resolve_reference(f"{base}.{expression.attr}") if base else None
        return None

    def _resolve_name(self, name: str, module: SourceModule) -> str | None:
        return self._resolve_reference(module.imports.get(name, f"{module.name}.{name}"))

    def _resolve_reference(self, reference: str, seen: set[str] | None = None) -> str | None:
        if reference.startswith("common."):
            reference = f"py4web.{reference}"
        if reference in self.classes or is_endow_injectable(reference):
            return reference
        module_name, separator, symbol = reference.rpartition(".")
        if not separator or module_name not in self.modules:
            return None
        seen = seen or set()
        if reference in seen:
            return None
        target = self.modules[module_name].imports.get(symbol)
        return self._resolve_reference(target, seen | {reference}) if target else None

    def _violate(self, node: ast.Call, code: str, message: str) -> None:
        self.violations.append(
            CustomLintViolation(
                path=self.module.path,
                line=node.lineno,
                column=node.col_offset + 1,
                code=code,
                message=message,
            )
        )


class RuntimeRequirementCollector:
    """Collect runtime inputs for one Endow graph without constructing it."""

    def __init__(self, linter: EndowCallLinter, provided: set[str]) -> None:
        """Store the graph resolver and call-site inputs that stop traversal."""
        self.linter = linter
        self.provided = provided
        self.requirements: list[tuple[str, tuple[str, ...]]] = []
        self.seen_classes: set[str] = set()
        self.seen_requirements: set[str] = set()

    def collect(self, class_key: str) -> list[tuple[str, tuple[str, ...]]]:
        """Return each requirement once, in source traversal order."""
        self._visit(class_key, ())
        return self.requirements

    def _visit(self, class_key: str, path: tuple[str, ...]) -> None:
        if class_key in self.seen_classes:
            return
        self.seen_classes.add(class_key)
        source_class = self.linter.classes[class_key]
        factory = self.linter._factory(source_class)
        self._add_factory_requirements(source_class, factory, path)

        for field_name, (field_module, annotation) in self.linter._fields(source_class).items():
            if field_name in self.provided:
                continue
            dependency = self.linter._resolve_expression(annotation, field_module)
            field_path = (*path, f"{source_class.node.name}.{field_name}")
            if dependency and self.linter._is_injectable(dependency):
                self._visit(dependency, field_path)
            elif factory is None:
                self._add(field_name, field_path)

    def _add_factory_requirements(
        self,
        source_class: SourceClass,
        factory: ast.FunctionDef | ast.AsyncFunctionDef | None,
        path: tuple[str, ...],
    ) -> None:
        if factory is None:
            return
        for argument in self.linter._required_factory_arguments(factory):
            self._add(argument, (*path, f"{source_class.node.name}.from_env({argument})"))

    def _add(self, name: str, path: tuple[str, ...]) -> None:
        if name in self.seen_requirements:
            return
        self.seen_requirements.add(name)
        self.requirements.append((name, path))


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


def check_endow_from_env(modules: dict[str, SourceModule], code: str, message: str) -> t.Sequence[CustomLintViolation]:
    """Find direct `from_env` calls on source-defined Endow injectables."""
    return EndowCallLinter(modules, {code}).lint()


def check_endow_runtime_inputs(
    modules: dict[str, SourceModule], code: str, message: str
) -> t.Sequence[CustomLintViolation]:
    """Find Endow construction calls missing declared runtime inputs."""
    return EndowCallLinter(modules, {code}).lint()


CUSTOM_LINT_RULES: tuple[CustomLintRule, ...] = (
    CustomLintRule(
        code="EW001",
        message="avoid monkeypatch.setattr; use a focused fixture or explicit test seam instead",
        checker=check_monkeypatch_setattr,
    ),
    CustomLintRule(
        code="EW002",
        message="call .with_injected(...) instead of direct Endow .from_env(...)",
        project_checker=check_endow_from_env,
    ),
    CustomLintRule(
        code="EW003",
        message="provide every Endow runtime input required by .with_injected(...)",
        project_checker=check_endow_runtime_inputs,
    ),
)


def discover_python_files(ctx: Context) -> list[Path]:
    """Discover Python files using ripgrep's ignore-aware file listing."""
    result = ctx.run("rg --files -g '*.py'", hide=True)
    return [Path(line) for line in result.stdout.splitlines()]


def module_name(path: Path) -> str:
    """Return the importable module name represented by a source path."""
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def import_bindings(tree: ast.Module, current_module: str, is_package: bool) -> dict[str, str]:
    """Map local import names to their fully qualified source references."""
    bindings: dict[str, str] = {}
    package = current_module.split(".")
    if not is_package:
        package.pop()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            base_parts = package[: len(package) - max(node.level - 1, 0)] if node.level else []
            if node.module:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{base}.{alias.name}" if base else alias.name

    return bindings


def source_modules(ctx: Context) -> dict[str, SourceModule]:
    """Parse the Python source tree once for custom static lint rules."""
    modules: dict[str, SourceModule] = {}
    for path in discover_python_files(ctx):
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        name = module_name(path)
        modules[name] = SourceModule(
            path=path,
            name=name,
            tree=tree,
            source=source,
            imports=import_bindings(tree, name, path.name == "__init__.py"),
        )
    return modules


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
    modules = source_modules(ctx)

    for module in modules.values():
        lines = module.source.splitlines()

        for rule in CUSTOM_LINT_RULES:
            if rule.checker is None:
                continue
            for violation in rule.checker(module.path, module.tree, rule.code, rule.message):
                if not is_suppressed(lines, violation):
                    violations.append(violation)

    for rule in CUSTOM_LINT_RULES:
        if rule.project_checker is None:
            continue
        for violation in rule.project_checker(modules, rule.code, rule.message):
            lines = modules[module_name(violation.path)].source.splitlines()
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
