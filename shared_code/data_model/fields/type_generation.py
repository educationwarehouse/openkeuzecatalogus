"""Shared rendering helpers for generated TypedDict modules."""

import types
import typing as t
from pathlib import Path


def render_python_type(annotation: t.Any) -> str:
    """Render a runtime model annotation as a Python type expression."""
    if isinstance(annotation, str):
        return annotation

    origin = t.get_origin(annotation)
    args = t.get_args(annotation)
    if origin in (t.Union, types.UnionType):
        return " | ".join(render_python_type(arg) for arg in args)
    elif origin is not None:
        return f"{origin.__name__}[{', '.join(render_python_type(arg) for arg in args)}]"
    elif annotation is type(None):
        return "None"
    elif getattr(annotation, "__module__", None) == "datetime":
        return f"dt.{annotation.__name__}"
    else:
        return annotation.__name__


def render_typed_dict(
    payload_name: str,
    description: str,
    fields: t.Mapping[str, t.Any],
) -> list[str]:
    """Render one generated TypedDict class."""
    return [
        f"class {payload_name}(t.TypedDict, total=False):",
        f'    """{description}"""',
        *[f"    {name}: {render_python_type(field_type)}" for name, field_type in fields.items()],
        "",
    ]


def write_generated(path: Path, contents: str) -> None:
    """Write one generated module only when its contents changed."""
    if path.exists() and path.read_text() == contents:
        print(f"Unchanged: {path}")
        return

    path.write_text(contents)
    print(f"Generated: {path}")
