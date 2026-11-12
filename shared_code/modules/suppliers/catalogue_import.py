"""Read and apply catalogue participation CSV files after explicit review."""

import csv
import io
import typing as t
import unicodedata
import uuid

from shared_code.data_model import Supplier, SupplierEd, update_effectivedated
from shared_code.data_model.constants.catalog import PARTICIPATION_LABELS

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_ROWS = 1000
HEADERS = (
    "officiele_naam",
    "edu_v_naam",
    "status",
)
IMPORT_STATUSES = {
    "participating": "Beschikbaar",
    "soon": "Binnenkort gedeeld",
    "in_conversation": "In gesprek",
    "unknown": "Onbekend",
}


class CatalogueImportRow(t.TypedDict):
    """Source data and editable proposals for one inventory supplier."""

    name: str
    import_name: str
    aliases: list[str]
    suggested_gid: str
    status: str
    candidates: list[str]


class CatalogueImportSelection(t.TypedDict):
    """Administrator's selected target and expectation for one source row."""

    target: str
    status: str


def normalized_supplier_name(value: str) -> str:
    """Match spelling variants without guessing at similar company names."""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if character.isalnum())


def csv_delimiter(text: str) -> str:
    """Accept Dutch Excel exports, which separate columns with semicolons instead of commas."""
    header = text.split("\n", 1)[0]

    return ";" if header.count(";") > header.count(",") else ","


def read_catalogue_csv(content: bytes) -> list[CatalogueImportRow]:
    """Validate a bounded UTF-8 CSV, ignoring additional columns."""
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Kies een CSV-bestand van maximaal 5 MB.")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Het bestand moet een UTF-8 CSV-bestand zijn.") from exc

    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=csv_delimiter(text), strict=True)
        return read_inventory_rows(reader)
    except csv.Error as exc:
        message = "Het CSV-bestand is niet leesbaar. Controleer de scheidingstekens en aanhalingstekens."
        raise ValueError(message) from exc


def read_inventory_rows(values: t.Iterator[list[str]]) -> list[CatalogueImportRow]:
    """Extract the three required columns and reject duplicate supplier identities."""
    headers = [value.strip() for value in next(values, [])]
    if any(headers.count(header) != 1 for header in HEADERS):
        raise ValueError(
            "De kolommen officiele_naam, edu_v_naam en status zijn verplicht en mogen niet dubbel voorkomen."
        )

    positions = [headers.index(header) for header in HEADERS]
    statuses = {label.casefold(): key for key, label in IMPORT_STATUSES.items()}
    rows: list[CatalogueImportRow] = []
    seen: set[str] = set()

    for row_number, values_row in enumerate(values, start=2):
        if not any(value.strip() for value in values_row):
            continue

        if len(rows) >= MAX_ROWS:
            raise ValueError("Het bestand mag maximaal 1000 aanbieders bevatten.")
        if len(values_row) <= max(positions):
            raise ValueError(f"Rij {row_number}: een verplichte kolom ontbreekt.")

        import_name, name, source_status = (values_row[position].strip() for position in positions)
        key = normalized_supplier_name(import_name)
        if not normalized_supplier_name(name) or not key or key in seen:
            raise ValueError(f"Rij {row_number}: ontbrekende naam of dubbele officiële naam.")

        status = statuses.get(source_status.casefold())
        if status is None:
            raise ValueError(
                f"Rij {row_number}: kies Beschikbaar, Binnenkort gedeeld, In gesprek of Onbekend als status."
            )

        seen.add(key)
        rows.append(
            CatalogueImportRow(
                name=name,
                import_name=import_name,
                aliases=[name],
                suggested_gid="",
                status=status,
                candidates=[],
            )
        )

    if not rows:
        raise ValueError("Het bestand bevat geen aanbieders.")
    return rows


def propose_supplier_matches(rows: list[CatalogueImportRow], suppliers: t.Iterable[Supplier]) -> None:
    """Match the Edu-V name against normalized platform and publisher names."""
    by_name: dict[str, set[str]] = {}
    for supplier in suppliers:
        gid = str(supplier.gid)
        for name in (supplier.name, supplier.endpoint_publisher):
            if name:
                by_name.setdefault(normalized_supplier_name(name), set()).add(gid)

    for row in rows:
        matches = set().union(*(by_name.get(normalized_supplier_name(name), set()) for name in row["aliases"]))

        row["candidates"] = sorted(matches)
        if len(matches) == 1:
            row["suggested_gid"] = next(iter(matches))
        elif not matches:
            row["suggested_gid"] = "new"


def validate_import_selections(
    rows: list[CatalogueImportRow],
    selections: list[CatalogueImportSelection],
    suppliers: dict[str, Supplier],
) -> None:
    """Reject ambiguous, stale or duplicate targets before creating any versions."""
    if len(rows) != len(selections):
        raise ValueError("De importselectie is onvolledig. Upload het bestand opnieuw.")

    used_targets: set[str] = set()
    new_names: set[str] = set()
    existing_names = {normalized_supplier_name(supplier.name) for supplier in suppliers.values()}
    for row, selection in zip(rows, selections, strict=True):
        target = selection["target"]
        if target == "skip":
            continue

        if selection["status"] not in PARTICIPATION_LABELS:
            raise ValueError(f"Ongeldige status voor {row['name']}.")

        if target == "new":
            name = normalized_supplier_name(row["name"])
            if name in existing_names or name in new_names:
                raise ValueError(f"{row['name']} bestaat al. Kies de bestaande aanbieder.")
            new_names.add(name)
        elif target not in suppliers:
            raise ValueError(f"Kies een bestaande of nieuwe aanbieder voor {row['name']}.")
        elif target in used_targets:
            raise ValueError("Meerdere CSV-regels zijn aan dezelfde aanbieder gekoppeld. Sla een dubbele regel over.")
        else:
            used_targets.add(target)


def apply_catalogue_import(
    db: DatabaseContext,
    rows: list[CatalogueImportRow],
    selections: list[CatalogueImportSelection],
    actor: str,
) -> dict[str, int]:
    """Insert effective-dated versions, preserving other supplier fields and history."""
    suppliers = {str(supplier.gid): supplier for supplier in Supplier.collect()}
    validate_import_selections(rows, selections, suppliers)
    result = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    for row, selection in zip(rows, selections, strict=True):
        target = selection["target"]
        if target == "skip":
            result["skipped"] += 1
            continue

        values = {
            "catalogue_participation_status": selection["status"],
        }
        if target == "new":
            SupplierEd.insert(name=row["name"], endpoint_type="none", last_saved_by=actor, **values)
            result["created"] += 1
        else:
            supplier = suppliers[target]
            if all(supplier[field] == value for field, value in values.items()):
                result["unchanged"] += 1
                continue

            update_effectivedated(
                db,
                SupplierEd,
                SupplierEd.gid == uuid.UUID(target),
                new_values=values,
                prio=supplier.prio,
                last_saved_by=actor,
            )
            result["updated"] += 1

    return result
