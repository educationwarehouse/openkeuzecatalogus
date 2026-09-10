"""AST checks for admin route guard decorators."""

import ast
import typing as t
from pathlib import Path

CONTROLLERS_DIR = Path(__file__).resolve().parents[1] / "apps" / "admin" / "controllers"
ALLOWED_ADMIN_ROUTE_FIXTURES: dict[str, str | set[str]] = {
    "admin": "*",
    "admin_or_supplier": "*",
    "common": {"stop_impersonate"},
}


def _decorator_name(node: ast.expr) -> str | None:
    """Return the dotted name for a decorator expression."""
    target = node.func if isinstance(node, ast.Call) else node
    parts: list[str] = []

    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value

    if isinstance(target, ast.Name):
        parts.append(target.id)
        return ".".join(reversed(parts))

    return None


def _is_route_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether the function declares at least one concrete route."""
    return any(_decorator_name(decorator) == "action" for decorator in node.decorator_list)


def _has_allowed_guard(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether the function uses an approved admin-route fixture decorator."""
    decorator_names = {_decorator_name(decorator) for decorator in node.decorator_list}

    for decorator_name in decorator_names:
        allowed_functions = ALLOWED_ADMIN_ROUTE_FIXTURES.get(t.cast(str, decorator_name))
        if allowed_functions == "*":
            return True
        if isinstance(allowed_functions, set) and node.name in allowed_functions:
            return True

    return False


def test_admin_routes_use_guard_decorator() -> None:
    """Every admin route handler must declare an approved fixture decorator."""
    missing_guards: list[str] = []

    for controller_path in sorted(CONTROLLERS_DIR.glob("*.py")):
        module = ast.parse(controller_path.read_text(), filename=str(controller_path))
        for node in module.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_route_handler(node):
                continue
            if _has_allowed_guard(node):
                continue
            missing_guards.append(
                f"{controller_path.relative_to(CONTROLLERS_DIR.parent.parent)}:{node.lineno} {node.name}"
            )

    assert not missing_guards, "Admin routes missing an approved fixture decorator:\n" + "\n".join(missing_guards)
