"""Generate public catalogue payload types from runtime model metadata."""

from pathlib import Path

from typedal.tables import TypedTable

from shared_code.data_model import Method, Product, Supplier
from shared_code.data_model.fields.public import is_public_readable_field
from shared_code.data_model.fields.type_generation import render_typed_dict, write_generated
from shared_code.infra.database import database_context

OUTPUT_PATH = Path(__file__).parents[2] / "generated" / "public_payloads.py"
PUBLIC_MODELS: dict[str, type[TypedTable]] = {
    "PublicMethod": Method,
    "PublicProduct": Product,
    "PublicSupplier": Supplier,
}


def render_public_payloads() -> str:
    """Render public TypedDict definitions from bound TypeDAL models."""
    lines = [
        '"""Generated public catalogue payload types. Do not edit manually."""',
        "",
        "import datetime as dt",
        "import typing as t",
        "",
    ]
    for payload_name, model in PUBLIC_MODELS.items():
        annotations = model.as_typeddict(
            include_relationships=False,
            include_properties=False,
        ).__annotations__
        fields = {
            name: annotations[name]
            for name in model.fields
            if name in annotations and is_public_readable_field(model, name)
        }
        lines.extend(
            render_typed_dict(
                payload_name,
                f"Generated public payload for {model.__name__}.",
                fields,
            )
        )
    return "\n".join(lines)


def main() -> None:
    """Write the generated public catalogue payload module."""
    with database_context("tasks.generate_publictypes"):
        contents = render_public_payloads()

    write_generated(OUTPUT_PATH, contents)


if __name__ == "__main__":
    main()
