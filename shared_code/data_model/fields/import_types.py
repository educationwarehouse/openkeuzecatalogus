"""Generate importer payload types from runtime model metadata."""

import typing as t
from pathlib import Path

from typedal.tables import TypedTable

from shared_code.data_model import MethodEd, ProductEd, SupplierEd, VisionEd
from shared_code.data_model.fields.type_generation import render_typed_dict, write_generated
from shared_code.infra.database import database_context

OUTPUT_PATH = Path(__file__).parents[2] / "generated" / "import_payloads.py"
IMPORT_MODELS: dict[str, type[TypedTable]] = {
    "ImportMethod": MethodEd,
    "ImportProduct": ProductEd,
    "ImportSupplier": SupplierEd,
    "ImportVision": VisionEd,
}
EXCLUDED_FIELD_NAMES = {"id", "created_at", "updated_at"}
EXTRA_FIELDS = {
    "ImportMethod": {"_errors": "list[ImportErrorCode]"},
    "ImportProduct": {
        "_errors": "list[ImportErrorCode]",
        "bundle_product_olids": "list[str]",
        "follow_up_product_olid": "str",
        "method_name": "str",
        "method_olid": "str",
        "related_product_olids": "list[str]",
    },
}
FIELD_OVERRIDES = {
    "ImportMethod": {"import_error_codes": "list[str] | list[ImportErrorCode]"},
    "ImportProduct": {
        "import_error_codes": "list[str] | list[ImportErrorCode]",
        "method_gid": "str | None",
    },
}


def _field_annotation(
    model: type[TypedTable],
    name: str,
    annotations: t.Mapping[str, t.Any],
) -> t.Any:
    """Return the value type produced by the model field's input filter."""
    annotation = annotations[name]
    if getattr(model[name], "filter_out", None) is not str:
        return annotation

    return "str | None" if type(None) in t.get_args(annotation) else "str"


def render_import_payloads() -> str:
    """Render importer TypedDict definitions from bound TypeDAL models."""
    lines = [
        '"""Generated importer payload types. Do not edit manually."""',
        "",
        "import datetime as dt",
        "import typing as t",
        "from shared_code.modules.scrapers.errors import ImportErrorCode",
        "",
    ]
    for payload_name, model in IMPORT_MODELS.items():
        annotations = model.as_typeddict(
            include_relationships=False,
            include_properties=False,
        ).__annotations__
        fields: dict[str, t.Any] = {
            name: _field_annotation(model, name, annotations)
            for name in model.fields
            if name in annotations and name not in EXCLUDED_FIELD_NAMES
        }
        fields.update(FIELD_OVERRIDES.get(payload_name, {}))
        fields.update(EXTRA_FIELDS.get(payload_name, {}))
        lines.extend(
            render_typed_dict(
                payload_name,
                f"Generated importer payload for {model.__name__}.",
                fields,
            )
        )
    return "\n".join(lines)


def main() -> None:
    """Write the generated importer payload module."""
    with database_context("tasks.generate_importtypes"):
        contents = render_import_payloads()

    write_generated(OUTPUT_PATH, contents)


if __name__ == "__main__":
    main()
