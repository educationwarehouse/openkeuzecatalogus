"""Supported school subjects and reconciliation of supplier-provided names."""

import typing as t

from shared_code.data_model import Method, Product, SchoolSubject, SchoolSubjectEd, update_effectivedated

from .names import normalize_school_subject
from .types import SchoolSubjectConflictError, SchoolSubjectUsage, SchoolSubjectValues, UnmatchedSchoolSubject

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext


def school_subject_name_lookup() -> dict[str, str]:
    """Resolve unambiguous names and aliases after normalizing case and whitespace."""
    candidates: dict[str, set[str]] = {}
    subjects = SchoolSubject.select(SchoolSubject.name, SchoolSubject.aliases).collect()

    for subject in subjects:
        for value in [subject.name, *(subject.aliases or [])]:
            normalized = normalize_school_subject(value)
            if normalized:
                candidates.setdefault(normalized, set()).add(subject.name)

    return {value: next(iter(names)) for value, names in candidates.items() if len(names) == 1}


def school_subjects_using(value: str) -> list[str]:
    """List the standard names of every subject whose name or alias matches a normalized value."""
    subjects = SchoolSubject.select(SchoolSubject.name, SchoolSubject.aliases, orderby=SchoolSubject.name).collect()

    return [
        subject.name
        for subject in subjects
        if value in {normalize_school_subject(item) for item in [subject.name, *(subject.aliases or [])]}
    ]


def clean_school_subject_values(
    name: str, aliases: t.Iterable[str], excluding_gid: str | None = None
) -> SchoolSubjectValues:
    """Validate names across the complete supported list before a new version."""
    name = name.strip()
    if not name or len(name) > 512:
        raise ValueError("Vul een standaardnaam van 1 tot en met 512 tekens in.")

    name_key = normalize_school_subject(name)
    distinct: dict[str, str] = {}
    for alias in aliases:
        if alias.strip():
            distinct.setdefault(normalize_school_subject(alias), alias.strip())

    distinct.pop(name_key, None)

    query = SchoolSubject.where()
    if excluding_gid is not None:
        query = query.where(SchoolSubject.gid != excluding_gid)

    for subject in query.select(SchoolSubject.name, SchoolSubject.aliases).collect():
        existing = {normalize_school_subject(value) for value in [subject.name, *(subject.aliases or [])]}
        if name_key in existing:
            raise SchoolSubjectConflictError(f"Deze standaardnaam wordt al gebruikt bij {subject.name}.", "name")

        if existing.intersection(distinct):
            raise SchoolSubjectConflictError(f"Een alias wordt al gebruikt bij {subject.name}.", "aliases")

    return SchoolSubjectValues(name=name, aliases=list(distinct.values()))


def create_school_subject(name: str, aliases: t.Iterable[str], last_saved_by: str) -> str:
    """Create a supported subject, including any original source names as aliases."""
    values = clean_school_subject_values(name, aliases)
    row = SchoolSubjectEd.insert(**values, last_saved_by=last_saved_by)
    assert row is not None, "Inserting a school subject with validated values should return the created row"
    return row.gid


def match_school_subject(db: DatabaseContext, raw_values: t.Iterable[str], target_gid: str, last_saved_by: str) -> str:
    """Add source spellings to an existing subject through a historical version."""
    subject = SchoolSubject.where(SchoolSubject.gid == target_gid).collect().first()
    if subject is None:
        raise ValueError("Het gekozen vak bestaat niet meer. Kies een ander vak.")

    values = clean_school_subject_values(
        subject.name, [*(subject.aliases or []), *raw_values], excluding_gid=subject.gid
    )
    if values["aliases"] != (subject.aliases or []):
        update_effectivedated(
            db,
            SchoolSubjectEd,
            where=SchoolSubjectEd.gid == subject.gid,
            new_values=dict(values),
            last_saved_by=last_saved_by,
        )
    return subject.gid


def unknown_subject_usages(
    rows: t.Iterable[SchoolSubjectUsage], supported: dict[str, str]
) -> t.Iterator[tuple[str, set[str], int]]:
    """Yield each unknown normalized subject per subject list, with its spellings and material count."""
    for row in rows:
        spellings: dict[str, set[str]] = {}
        for raw in row["subjects"]:
            normalized = normalize_school_subject(raw)
            if normalized and normalized not in supported:
                spellings.setdefault(normalized, set()).add(raw)

        for normalized, raw_values in spellings.items():
            yield normalized, raw_values, row["material_count"]


def count_unmatched_subjects(
    rows_by_kind: dict[t.Literal["product", "method"], t.Iterable[SchoolSubjectUsage]],
    supported: dict[str, str],
) -> dict[str, UnmatchedSchoolSubject]:
    """Count each material once per normalized unknown subject."""
    unmatched: dict[str, UnmatchedSchoolSubject] = {}

    for entity_kind, rows in rows_by_kind.items():
        for normalized, raw_values, material_count in unknown_subject_usages(rows, supported):
            item = unmatched.setdefault(normalized, UnmatchedSchoolSubject(value=normalized))
            item.raw_values.update(raw_values)
            if entity_kind == "product":
                item.product_count += material_count
            else:
                item.method_count += material_count

    return unmatched


def school_subject_usage(model: type[Product] | type[Method]) -> list[SchoolSubjectUsage]:
    """Count identical subject lists in the database, letting the ORM decode them."""
    count_field = model.id.count()
    rows = (
        model.where((model.available != "verwijderd") & (model.subjects != None))
        .select(model.subjects, count_field, groupby=model.subjects)
        .execute()
    )
    return [SchoolSubjectUsage(subjects=row[model.subjects], material_count=int(row[count_field])) for row in rows]


def unmatched_school_subjects() -> list[UnmatchedSchoolSubject]:
    """Read unknown subjects from available products and methods without rewrites."""
    supported = school_subject_name_lookup()
    product_rows = school_subject_usage(Product)
    method_rows = school_subject_usage(Method)

    unmatched = count_unmatched_subjects({"product": product_rows, "method": method_rows}, supported)
    return sorted(unmatched.values(), key=lambda item: item.label.casefold())
