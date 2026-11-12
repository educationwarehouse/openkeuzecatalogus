"""Database-backed subject filtering over unchanged supplier data."""

import dataclasses as dc
import typing as t
import uuid

import pytest
from typedal import QueryBuilder

from shared_code.data_model import (
    CatalogEntityKind,
    DynamicFilter,
    Method,
    MethodEd,
    Product,
    ProductEd,
    SchoolSubject,
    SchoolSubjectEd,
    Supplier,
)
from shared_code.data_model.setup import define_tables
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.catalog_filters import CatalogFilters, ResolvedCatalogFilters
from shared_code.modules.catalog_filters.school_subjects import SchoolSubjectFilterDefinition
from shared_code.modules.catalog_filters.types import FilterOption
from shared_code.modules.methods import MethodBackend
from shared_code.modules.products import ProductBackend
from shared_code.modules.school_subjects import (
    SchoolSubjectConflictError,
    clean_school_subject_values,
    create_school_subject,
    match_school_subject,
    normalize_school_subject,
    preferred_spelling,
    school_subject_name_lookup,
    school_subjects_using,
    unmatched_school_subjects,
)
from shared_code.services.caching import MemoryCacheService


@dc.dataclass
class SubjectFilterCatalogue:
    """An isolated public catalogue with original subject spellings."""

    entity_kind: CatalogEntityKind
    table: type[Product] | type[Method]
    subject: SchoolSubjectEd
    rows: dict[str, ProductEd | MethodEd]
    slug: str
    filters: CatalogFilters
    caching: MemoryCacheService

    def builder(self) -> QueryBuilder[t.Any]:
        """Limit option discovery and matching to this fixture's records."""
        return self.table.where(self.table.gid.belongs([row.gid for row in self.rows.values()]))

    def resolve(self, values: list[str] | None = None) -> ResolvedCatalogFilters:
        """Resolve the real metadata-driven filter, including its option cache."""
        params = {} if values is None else {self.slug: values}
        return self.filters.resolve(self.entity_kind, params=params, option_builder=self.builder())

    def definition(self, resolved: ResolvedCatalogFilters) -> SchoolSubjectFilterDefinition:
        """Find the subject filter selected through its actual database metadata."""
        definition = next(item for item in resolved.filters if item.slug == self.slug)
        assert isinstance(definition, SchoolSubjectFilterDefinition)
        return definition

    def matching_gids(self, resolved: ResolvedCatalogFilters) -> set[str]:
        """Execute the expanded subject predicates against the real list field."""
        return set(self.filters.apply(self.builder(), resolved).column(self.table.gid))


@pytest.fixture()
def school_subject_factory(
    db_per_file: DatabaseContext,
) -> t.Iterator[t.Callable[..., SchoolSubjectEd]]:
    """Create supported subjects and deactivate their latest versions on cleanup."""
    gids: list[str] = []

    def create_subject(name: str, aliases: list[str]) -> SchoolSubjectEd:
        row = SchoolSubjectEd.insert(name=name, aliases=aliases)
        assert row is not None
        gids.append(row.gid)
        db_per_file.commit()
        return row

    yield create_subject

    for gid in reversed(gids):
        current = SchoolSubject.where(SchoolSubject.gid == gid).collect().first()
        if current:
            current.delete_record()
    db_per_file.commit()


@pytest.fixture(params=("product", "method"))
def subject_catalogue(
    request: pytest.FixtureRequest,
    db_per_file: DatabaseContext,
    memory_caching: MemoryCacheService,
    school_subject_factory: t.Callable[..., SchoolSubjectEd],
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
) -> SubjectFilterCatalogue:
    """Seed both catalogue kinds with known, unknown and near-matching subjects."""
    entity_kind = t.cast(CatalogEntityKind, request.param)
    suffix = uuid.uuid4().hex[:8]
    subject = school_subject_factory(
        name=f"Filter Nederlands {suffix}",
        aliases=[f"Filter Nederlandse taal {suffix}"],
    )
    supplier = supplier_factory(name=f"Subject supplier {suffix}", email_domains=[f"{suffix}.example.test"])
    raw_values = {
        "canonical": subject.name,
        "casing": f"  {subject.name.upper()}  ",
        "alias": f" {subject.aliases[0].swapcase()} ",
        "unknown": f"Eigen les {suffix}",
        "unknown_casing": f" EIGEN LES {suffix.upper()} ",
        "partial": f"{subject.name} extra",
        "pending": f"Nieuwe bronnaam {suffix}",
        "unrelated": f"Ander vak {suffix}",
    }
    rows: dict[str, ProductEd | MethodEd] = {}
    for key, value in raw_values.items():
        method_subjects = [value] if entity_kind == "method" else []
        product_subjects = [value] if entity_kind == "product" else []
        method = method_factory(
            supplier_gid=supplier.gid,
            olid=f"subject-method-{suffix}-{key}",
            name=f"Subject method {suffix} {key}",
            subjects=method_subjects,
        )
        product = product_factory(
            supplier_gid=supplier.gid,
            method_gid=method.gid,
            olid=f"subject-product-{suffix}-{key}",
            name=f"Subject product {suffix} {key}",
            subjects=product_subjects,
        )
        rows[key] = product if entity_kind == "product" else method

    config = dynamic_filter_factory(
        slug="subject-integration",
        label="Schoolvak",
        filter_kind="dynamic",
        field_name="subjects",
        applies_to="both",
        widget_kind="select",
        sort_order=1,
    )
    table = Product if entity_kind == "product" else Method
    return SubjectFilterCatalogue(
        entity_kind=entity_kind,
        table=table,
        subject=subject,
        rows=rows,
        slug=config.slug,
        filters=CatalogFilters.with_injected(db=db_per_file, caching=memory_caching),
        caching=memory_caching,
    )


def test_subject_filter_groups_and_matches_variants_without_changing_source_data(
    subject_catalogue: SubjectFilterCatalogue,
) -> None:
    """One canonical option matches original names and aliases without a rewrite."""
    catalogue = subject_catalogue
    original = {row.gid: row.subjects for row in catalogue.rows.values()}
    resolved = catalogue.resolve([catalogue.subject.name.lower(), f" {catalogue.subject.aliases[0].upper()} "])
    definition = catalogue.definition(resolved)
    options = definition.options()

    assert definition.current_value == [catalogue.subject.name]
    assert options.count(FilterOption(value=catalogue.subject.name, label=catalogue.subject.name)) == 1
    assert not any(option.value == catalogue.subject.aliases[0] for option in options)
    assert catalogue.matching_gids(resolved) == {catalogue.rows[key].gid for key in ("canonical", "casing", "alias")}

    current = catalogue.builder().select(catalogue.table.gid, catalogue.table.subjects).collect()
    assert {row.gid: row.subjects for row in current} == original


def test_unknown_subjects_remain_selectable_and_group_casing_variants(
    subject_catalogue: SubjectFilterCatalogue,
) -> None:
    """Unrecognized subject spellings remain discoverable and filter correctly."""
    catalogue = subject_catalogue
    unknown = catalogue.rows["unknown"].subjects[0]
    resolved = catalogue.resolve([f" {unknown.upper()} "])
    definition = catalogue.definition(resolved)

    assert definition.current_value == [unknown.casefold()]
    assert sum(option.value == unknown.casefold() for option in definition.options()) == 1
    assert catalogue.matching_gids(resolved) == {
        catalogue.rows["unknown"].gid,
        catalogue.rows["unknown_casing"].gid,
    }


def test_multiple_subject_selections_match_whole_entries_with_or_semantics(
    subject_catalogue: SubjectFilterCatalogue,
) -> None:
    """Known and unknown groups combine without matching longer subject names."""
    catalogue = subject_catalogue
    resolved = catalogue.resolve([catalogue.subject.name, catalogue.rows["unknown"].subjects[0]])

    assert catalogue.matching_gids(resolved) == {
        catalogue.rows[key].gid for key in ("canonical", "casing", "alias", "unknown", "unknown_casing")
    }


def test_ambiguous_subject_alias_remains_an_independent_unknown_option(
    subject_catalogue: SubjectFilterCatalogue,
    school_subject_factory: t.Callable[..., SchoolSubjectEd],
    db_per_file: DatabaseContext,
) -> None:
    """An alias shared by two supported subjects never merges their groups."""
    catalogue = subject_catalogue
    ambiguous = catalogue.rows["pending"].subjects[0]
    catalogue.subject.update_record(aliases=[*catalogue.subject.aliases, ambiguous])
    school_subject_factory(name=f"Other {catalogue.subject.name}", aliases=[ambiguous])
    db_per_file.commit()
    resolved = catalogue.resolve([ambiguous.upper()])
    definition = catalogue.definition(resolved)

    assert definition.current_value == [ambiguous.casefold()]
    assert FilterOption(value=ambiguous.casefold(), label=ambiguous) in definition.options()
    assert catalogue.matching_gids(resolved) == {catalogue.rows["pending"].gid}


def test_alias_search_and_active_selection_survive_cached_options(
    subject_catalogue: SubjectFilterCatalogue,
) -> None:
    """A warm option cache still supports alias search and canonical selection."""
    catalogue = subject_catalogue
    catalogue.resolve()
    with catalogue.filters.options_cache(catalogue.entity_kind) as cache:
        assert cache.valid

    cached = catalogue.resolve()

    page = cached.option_page(catalogue.slug, f" {catalogue.subject.aliases[0].upper()} ", offset=0, limit=1)
    expected = FilterOption(value=catalogue.subject.name, label=catalogue.subject.name)
    assert page.options == [expected]
    assert not page.has_more

    selected = catalogue.resolve([catalogue.subject.aliases[0]])
    page = selected.option_page(catalogue.slug, catalogue.subject.aliases[0], offset=0, limit=1)
    assert page.options == []
    assert page.selected_options == [expected]
    assert catalogue.matching_gids(selected) == {catalogue.rows[key].gid for key in ("canonical", "casing", "alias")}


@pytest.mark.parametrize("change", ("alias", "name"))
def test_effective_dated_subject_changes_refresh_options_and_public_listing_cache(
    subject_catalogue: SubjectFilterCatalogue,
    db_per_file: DatabaseContext,
    change: str,
) -> None:
    """New subject versions invalidate warm option and real public listing caches."""
    catalogue = subject_catalogue
    backend_type = ProductBackend if catalogue.entity_kind == "product" else MethodBackend
    backend = backend_type.with_injected(
        db=db_per_file,
        caching=catalogue.caching,
        filters=catalogue.filters,
        auth_adapter=AuthAdapter.for_service("school-subject-cache-test"),
    )
    old_name = catalogue.subject.name
    old_aliases = list(catalogue.subject.aliases)

    def listing_gids() -> set[str]:
        resolved = catalogue.resolve([old_name])
        if isinstance(backend, ProductBackend):
            rows = backend.list_public_products(filters=resolved, sort="missing", page=1, limit=100)
        else:
            rows = backend.list_public_methods(filters=resolved, sort="missing", page=1, limit=100)
        return {row.gid for row in rows}

    initial_gids = {catalogue.rows[key].gid for key in ("canonical", "casing", "alias")}
    # first call fills the listing cache, second call must return the same result from the warm cache
    assert listing_gids() == initial_gids
    assert listing_gids() == initial_gids

    pending = catalogue.rows["pending"].subjects[0]
    new_name = old_name
    new_aliases = [*old_aliases, pending]
    if change == "name":
        new_name = f"{old_name} Nieuw"
        new_aliases.append(old_name)
    catalogue.subject.update_record(name=new_name, aliases=new_aliases)
    db_per_file.commit()

    options = catalogue.definition(catalogue.resolve()).options()
    assert FilterOption(value=new_name, label=new_name) in options
    assert not any(option.value == pending.casefold() for option in options)
    if change == "name":
        assert not any(option.value == old_name for option in options)
    assert listing_gids() == initial_gids | {catalogue.rows["pending"].gid}

    historical = SchoolSubjectEd.where(SchoolSubjectEd.gid == catalogue.subject.gid).collect()
    assert len(historical) == 2
    assert any(row.name == old_name and row.aliases == old_aliases for row in historical)


def test_package_listing_groups_subject_variants_and_excludes_single_products(
    db_per_file: DatabaseContext,
    memory_caching: MemoryCacheService,
    school_subject_factory: t.Callable[..., SchoolSubjectEd],
    supplier_factory: t.Callable[..., Supplier],
    method_factory: t.Callable[..., MethodEd],
    product_factory: t.Callable[..., ProductEd],
    dynamic_filter_factory: t.Callable[..., DynamicFilter],
) -> None:
    """The package tab filters packages by canonical subject, never single products with that subject."""
    suffix = uuid.uuid4().hex[:8]
    subject = school_subject_factory(
        name=f"Pakket Nederlands {suffix}",
        aliases=[f"Pakket Nederlandse taal {suffix}"],
    )
    supplier = supplier_factory(name=f"Package subject supplier {suffix}", email_domains=[f"{suffix}.example.test"])
    method = method_factory(
        supplier_gid=supplier.gid,
        olid=f"package-subject-method-{suffix}",
        name=f"Package subject method {suffix}",
    )

    raw_values = {
        "canonical": ("package", subject.name),
        "alias": ("package", f" {subject.aliases[0].upper()} "),
        "unrelated": ("package", f"Ander vak {suffix}"),
        "single": ("single", subject.name),
    }
    rows: dict[str, ProductEd] = {}
    for key, (composition, value) in raw_values.items():
        rows[key] = product_factory(
            supplier_gid=supplier.gid,
            method_gid=method.gid,
            olid=f"package-subject-{suffix}-{key}",
            name=f"Package subject {suffix} {key}",
            composition=composition,
            subjects=[value],
        )

    config = dynamic_filter_factory(
        slug="package-subject-integration",
        label="Schoolvak",
        filter_kind="dynamic",
        field_name="subjects",
        applies_to="package",
        widget_kind="select",
        sort_order=1,
    )
    backend = ProductBackend.with_injected(
        db=db_per_file,
        caching=memory_caching,
        filters=CatalogFilters.with_injected(db=db_per_file, caching=memory_caching),
        auth_adapter=AuthAdapter.for_service("package-subject-test"),
    )

    resolved = backend.resolve_public_product_filters({config.slug: [subject.name.lower()]}, catalog_kind="package")
    definition = next(item for item in resolved.filters if item.slug == config.slug)
    assert isinstance(definition, SchoolSubjectFilterDefinition)
    assert definition.current_value == [subject.name]

    rows_found = backend.list_public_products(
        filters=resolved, sort="missing", page=1, limit=100, catalog_kind="package"
    )
    assert {row.gid for row in rows_found} == {rows["canonical"].gid, rows["alias"].gid}


def test_unmatched_subjects_group_variants_count_materials_once_and_skip_removed_rows(
    subject_catalogue: SubjectFilterCatalogue,
    db_per_file: DatabaseContext,
) -> None:
    """The reconciliation overview counts materials rather than repeated list entries."""
    catalogue = subject_catalogue
    unknown = catalogue.rows["unknown"].subjects[0]
    removed = catalogue.rows["unrelated"].subjects[0]
    catalogue.rows["unknown"].update_record(subjects=[unknown, unknown.upper(), unknown])
    catalogue.rows["unrelated"].update_record(available="verwijderd")
    db_per_file.commit()

    unmatched = {item.value: item for item in unmatched_school_subjects()}
    assert catalogue.subject.name.casefold() not in unmatched
    assert catalogue.subject.aliases[0].casefold() not in unmatched
    assert removed.casefold() not in unmatched
    item = unmatched[unknown.casefold()]
    assert unknown in item.raw_values
    assert unknown.upper() in item.raw_values
    if catalogue.entity_kind == "product":
        assert (item.product_count, item.method_count) == (2, 0)
    else:
        assert (item.product_count, item.method_count) == (0, 2)


def test_matching_unmatched_subject_preserves_source_data_and_adds_historical_version(
    subject_catalogue: SubjectFilterCatalogue,
    db_per_file: DatabaseContext,
) -> None:
    """Matching a group adds an alias and immediately changes the catalogue filters."""
    catalogue = subject_catalogue
    original = {row.gid: list(row.subjects) for row in catalogue.rows.values()}
    unknown = catalogue.rows["unknown"].subjects[0]
    catalogue.resolve()
    matched_gid = match_school_subject(
        db_per_file,
        [unknown, f" {unknown.upper()} "],
        catalogue.subject.gid,
        last_saved_by="test/subject-reconciliation",
    )
    db_per_file.commit()

    assert matched_gid == catalogue.subject.gid
    assert unknown.casefold() not in {item.value for item in unmatched_school_subjects()}
    resolved = catalogue.resolve([catalogue.subject.name])
    assert catalogue.matching_gids(resolved) == {
        catalogue.rows[key].gid for key in ("canonical", "casing", "alias", "unknown", "unknown_casing")
    }
    current = catalogue.builder().select(catalogue.table.gid, catalogue.table.subjects).collect()
    assert {row.gid: row.subjects for row in current} == original

    versions = SchoolSubjectEd.where(SchoolSubjectEd.gid == matched_gid).collect()
    assert len(versions) == 2
    assert any(unknown in row.aliases and row.last_saved_by == "test/subject-reconciliation" for row in versions)
    assert any(unknown not in row.aliases for row in versions)


def test_creating_supported_subject_resolves_original_name_through_an_alias(
    subject_catalogue: SubjectFilterCatalogue,
    db_per_file: DatabaseContext,
) -> None:
    """A new canonical name resolves a raw group without rewriting its material."""
    catalogue = subject_catalogue
    raw = catalogue.rows["pending"].subjects[0]
    name = f"Standaard {raw}"
    gid = create_school_subject(name, [raw, f" {raw.upper()} "], last_saved_by="test/create-subject")
    try:
        db_per_file.commit()
        supported = SchoolSubject.where(SchoolSubject.gid == gid).collect().first()
        assert supported is not None
        assert supported.name == name
        assert supported.aliases == [raw]
        assert raw.casefold() not in {item.value for item in unmatched_school_subjects()}
        resolved = catalogue.resolve([raw.upper()])
        assert catalogue.definition(resolved).current_value == [name]
        assert catalogue.matching_gids(resolved) == {catalogue.rows["pending"].gid}
        assert catalogue.builder().where(catalogue.table.gid == catalogue.rows["pending"].gid).column(
            catalogue.table.subjects
        ) == [[raw]]
    finally:
        supported = SchoolSubject.where(SchoolSubject.gid == gid).collect().first()
        if supported:
            supported.delete_record()
        db_per_file.commit()


@pytest.mark.parametrize("collision", ("name", "alias"))
def test_reconciliation_rejects_names_already_supported_with_different_casing(
    subject_catalogue: SubjectFilterCatalogue,
    collision: str,
) -> None:
    """Admin create actions cannot introduce an ambiguous name or alias."""
    catalogue = subject_catalogue
    name = catalogue.subject.name if collision == "name" else catalogue.subject.aliases[0]

    before = SchoolSubjectEd.count()
    with pytest.raises(ValueError, match="wordt al gebruikt"):
        create_school_subject(f" {name.upper()} ", [], last_saved_by="test/duplicate-subject")
    assert SchoolSubjectEd.count() == before


def test_subject_names_compare_without_case_or_repeated_whitespace() -> None:
    """Supplier spellings with doubled or surrounding whitespace normalize to one value."""
    assert normalize_school_subject("  Dronetechniek II:  inspecteren ") == "dronetechniek ii: inspecteren"
    assert preferred_spelling(["EIGEN LES", "Eigen  les", " eigen les"]) == "Eigen les"


def test_name_lookup_matches_spellings_with_different_internal_whitespace(
    school_subject_factory: t.Callable[..., SchoolSubjectEd],
) -> None:
    """A supported name with a doubled space still matches its single-spaced supplier spelling."""
    suffix = uuid.uuid4().hex[:8]
    subject = school_subject_factory(name=f"Dronetechniek II:  inspecteren {suffix}", aliases=[])

    lookup = school_subject_name_lookup()

    assert lookup[f"dronetechniek ii: inspecteren {suffix}"] == subject.name


@pytest.mark.parametrize(("collision", "field"), (("name", "name"), ("alias", "aliases")))
def test_subject_conflicts_name_the_form_field_that_caused_them(
    school_subject_factory: t.Callable[..., SchoolSubjectEd],
    collision: str,
    field: str,
) -> None:
    """Grid validation can attach a conflict to the standard name or to the aliases."""
    suffix = uuid.uuid4().hex[:8]
    existing = school_subject_factory(name=f"Bestaand vak {suffix}", aliases=[f"Bestaande alias {suffix}"])

    if collision == "name":
        name, aliases = existing.aliases[0], []
    else:
        name, aliases = f"Nieuw vak {suffix}", [existing.name.upper()]

    with pytest.raises(SchoolSubjectConflictError) as conflict:
        clean_school_subject_values(name, aliases)

    assert conflict.value.field == field


def test_subjects_using_an_ambiguous_alias_are_listed_for_reconciliation(
    school_subject_factory: t.Callable[..., SchoolSubjectEd],
) -> None:
    """The resolve page can name every subject that shares an ambiguous alias."""
    suffix = uuid.uuid4().hex[:8]
    alias = f"Gedeelde alias {suffix}"
    first = school_subject_factory(name=f"Eerste vak {suffix}", aliases=[alias])
    second = school_subject_factory(name=f"Tweede vak {suffix}", aliases=[f" {alias.upper()} "])

    assert school_subjects_using(normalize_school_subject(alias)) == [first.name, second.name]
