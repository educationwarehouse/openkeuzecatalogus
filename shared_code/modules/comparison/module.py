"""Public comparison data assembly."""

import json
import typing as t

from endow import Domain
from typedal.tables import TypedRow

from shared_code.data_model import Method, Product, Supplier
from shared_code.data_model.constants import get_themes
from shared_code.data_model.fields import is_public_readable_field
from shared_code.modules.catalog_filters import CatalogEntityKind
from shared_code.modules.comparison.types import (
    ComparisonField,
    ComparisonPage,
    ComparisonRecord,
    ComparisonVision,
    ComparisonVisionValue,
    VisionIds,
)
from shared_code.modules.methods import MethodBackend
from shared_code.modules.products import ProductBackend
from shared_code.modules.visions import VisionBackend
from shared_code.services import Applogger
from shared_code.util.types import Ordered


class ComparisonBackend(Domain):
    """Load public catalogue records and their resolved visions for comparison."""

    methods: MethodBackend
    products: ProductBackend
    applog: Applogger
    visions: VisionBackend

    def load_public_comparison(self, entity_kind: CatalogEntityKind, gids: Ordered[str]) -> ComparisonPage:
        """Return selected public records in URL order with their comparison payload."""
        rows = (
            self.methods.list_public_methods_for_comparison(gids)
            if entity_kind == "method"
            else self.products.list_public_products_for_comparison(gids)
        )
        rows_by_gid = {row.gid: row for row in rows}
        ordered_rows = [rows_by_gid[gid] for gid in gids if gid in rows_by_gid]
        visions_by_gid, vision_ids = self._comparison_visions(ordered_rows, entity_kind)
        fields_by_gid = {row.gid: self._comparison_field_values(row, entity_kind) for row in ordered_rows}
        fields = self._comparison_fields(ordered_rows, entity_kind, fields_by_gid)
        visions = self._comparison_vision_rows(ordered_rows, visions_by_gid)

        self.applog.log_catalog_compare(
            entity_kind,
            requested_gids=gids,
            rows=ordered_rows,
            vision_ids=vision_ids,
        )
        return {
            "records": [self._comparison_record(row) for row in ordered_rows],
            "fields": fields,
            "visions": visions,
            "missing_count": len(gids) - len(ordered_rows),
        }

    @classmethod
    def _comparison_field_values(cls, row: TypedRow, entity_kind: CatalogEntityKind) -> dict[str, str]:
        table = Method if entity_kind == "method" else Product

        record = {name: row[name] for name in table.fields if is_public_readable_field(table, name)}
        record["supplier"] = row.supplier.name or "—"
        record.pop("supplier_gid", None)
        if entity_kind == "product":
            record["method"] = row.method.name or "—"
            record.pop("method_gid", None)

        def default_represent(value: t.Any, _: TypedRow) -> str:
            return (
                "—"
                if value is None
                else json.dumps(value, ensure_ascii=False, indent=2, default=str)
                if isinstance(value, (dict, list))
                else str(value)
            )

        def comparison_field(name: str, value: t.Any) -> str:
            fld = getattr(table, name, None)
            represent = getattr(fld, "represent", None) or default_represent

            return represent(value, row)

        return {name: comparison_field(name, value) for name, value in record.items()}

    @classmethod
    def _comparison_fields(
        cls,
        rows: list[Method | Product],
        entity_kind: CatalogEntityKind,
        fields_by_gid: dict[str, dict[str, str]],
    ) -> list[ComparisonField]:
        """Transpose record fields into display rows and mark changed values."""
        field_names = dict.fromkeys(name for row in rows for name in fields_by_gid[row.gid])
        result: list[ComparisonField] = []
        for name in field_names:
            label = cls._field_label(entity_kind, name)
            values = [fields_by_gid[row.gid].get(name, "—") for row in rows]
            result.append({"name": name, "label": label, "values": values, "different": len(set(values)) > 1})

        return result

    @classmethod
    def _comparison_record(cls, row: TypedRow) -> ComparisonRecord:
        """Convert a public ORM row into a comparison column heading."""
        return {
            "gid": row["gid"],
            "name": row.get("name") or row["gid"],
            "image_url": row.get("image_url") or "",
        }

    @classmethod
    def _field_label(cls, entity_kind: CatalogEntityKind, name: str) -> str:
        """Return the model's human-readable label, with a readable fallback."""
        relationship_labels = {"supplier": "Aanbieder", "method": "Methode"}
        if label := relationship_labels.get(name):
            return label

        table = Method if entity_kind == "method" else Product
        return str(getattr(getattr(table, name, None), "label", None) or name.replace("_", " ").capitalize())

    def _comparison_visions(
        self, rows: list[Method | Product], entity_kind: CatalogEntityKind
    ) -> tuple[dict[str, list[ComparisonVisionValue]], VisionIds]:
        """Resolve every theme from a method first, then its supplier."""
        sources = {
            row.gid: (
                t.cast(Method, row if entity_kind == "method" else row.method),
                t.cast(Supplier, row.supplier),
            )
            for row in rows
        }
        resolved_by_gid, vision_ids = self.visions.resolve_public_visions(sources)
        result: dict[str, list[ComparisonVisionValue]] = {
            gid: [
                ComparisonVisionValue(
                    source=vision["source"],
                    content=vision["content"],
                    properties=json.dumps(
                        vision["properties"],
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                )
                for vision in visions
            ]
            for gid, visions in resolved_by_gid.items()
        }
        return result, vision_ids

    @classmethod
    def _comparison_vision_rows(
        cls,
        rows: list[Method | Product],
        visions_by_gid: dict[str, list[ComparisonVisionValue]],
    ) -> list[ComparisonVision]:
        """Transpose resolved visions into their education-quality theme rows."""
        return [
            {
                "theme": title,
                "values": [visions_by_gid[row.gid][index] for row in rows],
                "different": len({tuple(visions_by_gid[row.gid][index].values()) for row in rows}) > 1,
            }
            for index, title in enumerate(get_themes().values())
        ]
