"""Project-specific lint tasks."""

import ast
import dataclasses
import importlib
import re
import typing as t
from pathlib import Path

from endow import GraphBuilder, Injectable
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


@dataclasses.dataclass(frozen=True)
class SourceFunction:
    """A source function declaration that can be resolved from a call site."""

    key: str
    module: SourceModule
    node: ast.FunctionDef | ast.AsyncFunctionDef
    owner_class: str | None = None


def resolve_endow_symbol(reference: str) -> type | None:
    """Return the Endow class a dotted reference names, or None for anything else."""
    if not reference.startswith("endow."):
        return None

    module_name, _, name = reference.rpartition(".")
    candidate = getattr(importlib.import_module(module_name), name, None)
    return candidate if isinstance(candidate, type) else None


def is_endow_injectable(reference: str) -> bool:
    """Return whether an Endow symbol is an `Injectable` subclass."""
    candidate = resolve_endow_symbol(reference)
    return candidate is not None and issubclass(candidate, Injectable)


def is_endow_graph_handle(reference: str) -> bool:
    """Return whether an Endow symbol is the handle Endow passes to a factory itself.

    Asked of Endow rather than matched by name, so the rule follows the package
    instead of restating it.
    """
    candidate = resolve_endow_symbol(reference)
    return candidate is not None and issubclass(candidate, GraphBuilder)


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

    def _factory(self, source_class: SourceClass) -> SourceFunction | None:
        """Return the `from_env` a class uses, inherited or its own.

        Carries the module the factory was declared in, because an inherited one
        resolves its annotations against that module's imports, not the
        subclass's.
        """
        for node in source_class.node.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "from_env":
                return SourceFunction(
                    key=f"{source_class.key}.from_env",
                    module=source_class.module,
                    node=node,
                    owner_class=source_class.key,
                )
        for base_key in self._bases(source_class):
            if base_key in self.classes:
                factory = self._factory(self.classes[base_key])
                if factory:
                    return factory
        return None

    def _is_graph_handle(self, argument: ast.arg, module: SourceModule) -> bool:
        """Report whether a factory parameter is Endow's handle to the graph.

        Such a parameter is not a runtime input: Endow supplies it to the
        factory, so a call site has nothing to pass and must not be asked for it.
        """
        if argument.annotation is None:
            return False

        reference = self._resolve_expression(argument.annotation, module)
        return reference is not None and is_endow_graph_handle(reference)

    def _required_factory_arguments(self, factory: SourceFunction) -> tuple[str, ...]:
        arguments = factory.node.args
        positional = (*arguments.posonlyargs, *arguments.args)
        positional = positional[1:] if positional else ()
        defaults = len(arguments.defaults)
        required_positional = positional[:-defaults] if defaults else positional
        required_keyword = tuple(
            argument
            for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
            if default is None
        )
        return tuple(
            argument.arg
            for argument in (*required_positional, *required_keyword)
            if not self._is_graph_handle(argument, factory.module)
        )

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
        return any(self._is_injectable(base, seen=seen | {class_key}) for base in self._bases(self.classes[class_key]))

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
        if reference in self.classes or is_endow_injectable(reference) or is_endow_graph_handle(reference):
            return reference
        module_name, separator, symbol = reference.rpartition(".")
        if not separator or module_name not in self.modules:
            return None
        seen = seen or set()
        if reference in seen:
            return None
        target = self.modules[module_name].imports.get(symbol)
        return self._resolve_reference(target, seen=seen | {reference}) if target else None

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
        factory: SourceFunction | None,
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


def check_bare_star_default_arguments(
    path: Path, tree: ast.AST, code: str, message: str
) -> t.Sequence[CustomLintViolation]:
    """Find defaulted keyword-only arguments introduced by a bare ``*``."""
    violations: list[CustomLintViolation] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.args.vararg is not None:
            continue
        if not node.args.kwonlyargs or node.args.kw_defaults[0] is None:
            continue
        argument = node.args.kwonlyargs[0]
        violations.append(
            CustomLintViolation(
                path=path,
                line=argument.lineno,
                column=argument.col_offset + 1,
                code=code,
                message=message,
            )
        )

    return violations


class DefaultArgumentCallLinter(ast.NodeVisitor):
    """Find resolvable project calls that pass defaulted parameters positionally."""

    def __init__(self, modules: dict[str, SourceModule], code: str, message: str) -> None:
        """Index project function declarations for call-site inspection."""
        self.modules = modules
        self.code = code
        self.message = message
        self.classes = self._discover_classes()
        self.functions = self._discover_functions()
        self.class_keys: list[str] = []
        self.module: SourceModule
        self.violations: list[CustomLintViolation] = []

    def _discover_classes(self) -> set[str]:
        return {
            f"{module.name}.{node.name}"
            for module in self.modules.values()
            for node in module.tree.body
            if isinstance(node, ast.ClassDef)
        }

    def _discover_functions(self) -> dict[str, SourceFunction]:
        functions: dict[str, SourceFunction] = {}
        for module in self.modules.values():
            for node in module.tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    key = f"{module.name}.{node.name}"
                    functions[key] = SourceFunction(key, module, node)
                elif isinstance(node, ast.ClassDef):
                    class_key = f"{module.name}.{node.name}"
                    for member in node.body:
                        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            key = f"{class_key}.{member.name}"
                            functions[key] = SourceFunction(key, module, member, class_key)
        return functions

    def lint(self) -> list[CustomLintViolation]:
        """Return violations from each resolvable project call."""
        for module in self.modules.values():
            self.module = module
            self.class_keys = []
            self.visit(module.tree)
        return self.violations

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track the source class for ``self`` and ``cls`` method calls."""
        self.class_keys.append(f"{self.module.name}.{node.name}")
        self.generic_visit(node)
        self.class_keys.pop()

    def visit_Call(self, node: ast.Call) -> None:
        """Report positional arguments that map to defaulted source parameters."""
        function = self._resolve_call(node.func)
        if function is not None and not any(isinstance(argument, ast.Starred) for argument in node.args):
            for position, parameter in self._defaulted_positional_parameters(function):
                if position < len(node.args):
                    argument = node.args[position]
                    self.violations.append(
                        CustomLintViolation(
                            path=self.module.path,
                            line=argument.lineno,
                            column=argument.col_offset + 1,
                            code=self.code,
                            message=f"{self.message}: {parameter}",
                        )
                    )
        self.generic_visit(node)

    def _resolve_call(self, expression: ast.expr) -> SourceFunction | None:
        reference = self._expression_reference(expression)
        if reference is None:
            return None
        resolved = self._resolve_reference(reference)
        if resolved in self.functions:
            return self.functions[resolved]
        if resolved in self.classes:
            return self.functions.get(f"{resolved}.__init__")
        return None

    def _expression_reference(self, expression: ast.expr) -> str | None:
        if isinstance(expression, ast.Name):
            if expression.id in {"self", "cls"} and self.class_keys:
                return self.class_keys[-1]
            return self.module.imports.get(expression.id, f"{self.module.name}.{expression.id}")
        if isinstance(expression, ast.Attribute):
            base = self._expression_reference(expression.value)
            return f"{base}.{expression.attr}" if base else None
        return None

    def _resolve_reference(self, reference: str, seen: set[str] | None = None) -> str | None:
        if reference in self.functions or reference in self.classes:
            return reference
        module_name, separator, symbol = reference.rpartition(".")
        if not separator or module_name not in self.modules:
            return None
        seen = seen or set()
        if reference in seen:
            return None
        target = self.modules[module_name].imports.get(symbol)
        return self._resolve_reference(target, seen=seen | {reference}) if target else None

    def _defaulted_positional_parameters(self, function: SourceFunction) -> tuple[tuple[int, str], ...]:
        arguments = function.node.args
        declaration_line = function.module.source.splitlines()[function.node.lineno - 1]
        if {"ALL", self.code} & noqa_codes(declaration_line):
            return ()
        positional = [*arguments.posonlyargs, *arguments.args]
        defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
        receiver_count = int(
            function.owner_class is not None and not DefaultArgumentCallLinter._is_staticmethod(function.node)
        )
        parameters: list[tuple[int, str]] = []
        for index, (argument, default) in enumerate(zip(positional, defaults, strict=True)):
            if index < receiver_count or argument not in arguments.args or default is None:
                continue
            parameters.append((index - receiver_count, argument.arg))
        return tuple(parameters)

    @staticmethod
    def _is_staticmethod(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return any(
            isinstance(decorator, ast.Name) and decorator.id == "staticmethod" for decorator in node.decorator_list
        )


def check_default_arguments_passed_positionally(
    modules: dict[str, SourceModule], code: str, message: str
) -> t.Sequence[CustomLintViolation]:
    """Find project calls that pass defaulted parameters positionally."""
    return DefaultArgumentCallLinter(modules, code, message).lint()


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
    CustomLintRule(
        code="EW004",
        message="do not use a bare * before a defaulted parameter",
        checker=check_bare_star_default_arguments,
    ),
    CustomLintRule(
        code="EW005",
        message="pass defaulted parameters by keyword",
        project_checker=check_default_arguments_passed_positionally,
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


def _module_lint_violations(module: SourceModule) -> list[CustomLintViolation]:
    """Run per-module rules and filter locally suppressed violations."""
    violations: list[CustomLintViolation] = []
    lines = module.source.splitlines()
    for rule in CUSTOM_LINT_RULES:
        if rule.checker is None:
            continue
        for violation in rule.checker(module.path, module.tree, rule.code, rule.message):
            if not is_suppressed(lines, violation):
                violations.append(violation)
    return violations


def custom_lint_violations(ctx: Context) -> list[CustomLintViolation]:
    """Run all custom lint rules and return unsuppressed violations."""
    violations: list[CustomLintViolation] = []
    modules = source_modules(ctx)

    for module in modules.values():
        violations.extend(_module_lint_violations(module))

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
