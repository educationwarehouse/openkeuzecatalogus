"""Tests for generated TypedDict rendering helpers."""

import datetime as dt
import typing as t
from pathlib import Path

from typedal import TypeDAL

from shared_code.data_model.fields.import_types import render_import_payloads
from shared_code.data_model.fields.public_types import render_public_payloads
from shared_code.data_model.fields.type_generation import (
    render_python_type,
    render_typed_dict,
    write_generated,
)


class _CustomType:
    """A module-local type used to exercise the generic rendering fallback."""


def test_render_python_type_handles_builtins_generics_and_forward_refs() -> None:
    """Runtime annotations render to deterministic Python type expressions."""
    assert render_python_type(str) == "str"
    assert render_python_type(int | str) == "int | str"
    assert render_python_type(list[int]) == "list[int]"
    assert render_python_type(type(None)) == "None"
    assert render_python_type(dt.datetime) == "dt.datetime"
    assert render_python_type("ForwardRef") == "ForwardRef"
    assert render_python_type(_CustomType) == "_CustomType"


def test_render_typed_dict_builds_stable_class_block() -> None:
    """A TypedDict class renders its header, docstring, fields, and trailing blank line."""
    assert render_typed_dict(
        "PublicMethod",
        "Public payload for Method.",
        {"name": str, "levels": list[str]},
    ) == [
        "class PublicMethod(t.TypedDict, total=False):",
        '    """Public payload for Method."""',
        "    name: str",
        "    levels: list[str]",
        "",
    ]


def test_write_generated_writes_only_when_contents_change(tmp_path: Path) -> None:
    """Generated modules are written on change and left alone when unchanged."""
    target = tmp_path / "generated.py"
    contents = "from typing import TypedDict\n"

    write_generated(target, contents)
    assert target.read_text() == contents

    write_generated(target, contents)
    assert target.read_text() == contents


def test_payload_type_renderers_include_import_fields_and_exclude_private_public_fields(
    db_per_file: TypeDAL,
) -> None:
    """Generated payload definitions retain importer extras without exposing internal public fields."""
    assert db_per_file is not None

    import_payloads = render_import_payloads()
    public_payloads = render_public_payloads()

    assert "class ImportProduct(t.TypedDict, total=False):" in import_payloads
    assert "    method_gid: str | None" in import_payloads
    assert "    bundle_product_olids: list[str]" in import_payloads
    assert "    _errors: list[ImportErrorCode]" in import_payloads
    assert "    id:" not in import_payloads

    assert "class PublicProduct(t.TypedDict, total=False):" in public_payloads
    assert "    recommended_price: float" in public_payloads
    assert "    gid: str" in public_payloads
    assert "    method_gid: str" in public_payloads
    assert "    supplier_gid: str" in public_payloads
