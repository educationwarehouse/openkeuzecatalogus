"""Validation helpers for persisted catalogue sort expressions."""

import typing as t

from shared_code.data_model.tables.method import Method
from shared_code.data_model.tables.product import Product

type CatalogSortTable = type[Product] | type[Method]


def parse_sort_expression(
    table: CatalogSortTable,
    order_expression: str,
) -> tuple[t.Any, dict[str, list[str]]]:
    """Parse a persisted order expression into a typed orderby value."""
    issues: dict[str, list[str]] = {}
    normalized = order_expression.strip()
    if not normalized:
        issues["other"] = ["no expression passed"]
        return None, issues

    if normalized == "random":
        return "random", issues

    parsed_fields: list[t.Any] = []
    for raw_part in normalized.split(","):
        part = raw_part.strip()
        if not part:
            continue

        descending = part.startswith("~")
        field_name = part[1:] if descending else part
        if field_name not in table.fields:
            issues["fields"] = [field_name]
            return None, issues

        field = table[field_name]
        parsed_fields.append(~field if descending else field)

    if not parsed_fields:
        issues["other"] = ["no sortable fields parsed"]
        return None, issues

    if len(parsed_fields) == 1:
        return parsed_fields[0], issues

    return tuple(parsed_fields), issues


# noinspection PyPep8Naming
class IS_SORT_EXPRESSION:
    """Validate a DynamicSort order expression against known catalogue tables."""

    def __init__(self, error_message: str = "Ongeldige order expressie") -> None:
        """Initialize the validator with an optional error-message prefix."""
        self.error_message = error_message

    def __call__(self, value: str, record_id: int | None = None) -> tuple[str | None, str | None]:
        """Validate a sort expression and return the cleaned value or an error."""
        from shared_code.data_model.tables.dynamic_sort import DynamicSort

        candidate = value.strip()
        if not candidate:
            return None, self.error_message

        applies_to = None
        if record_id is not None:
            row = DynamicSort(record_id)
            applies_to = str(row.applies_to) if row and row.applies_to else None

        if applies_to == "product":
            tables: tuple[CatalogSortTable, ...] = (Product,)
        elif applies_to == "method":
            tables = (Method,)
        elif applies_to == "both":
            tables = (Product, Method)
        else:
            tables = (Product, Method)

        parsed_results = [parse_sort_expression(table, candidate) for table in tables]
        if all(parsed_order is not None for parsed_order, _ in parsed_results):
            return candidate, None

        if record_id is None and any(parsed_order is not None for parsed_order, _ in parsed_results):
            return candidate, None

        field_issues = sorted({field for _, issues in parsed_results for field in issues.get("fields", [])})
        if field_issues:
            wrong_fields = ", ".join(field_issues)
            return None, f"{self.error_message}: onbekend veld {wrong_fields}"

        other_issues = [issue for _, issues in parsed_results for issue in issues.get("other", [])]
        if other_issues:
            return None, f"{self.error_message}: {other_issues[0]}"

        return None, self.error_message
