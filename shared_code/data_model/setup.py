"""Database table setup entrypoint for shared data models."""

from typedal import TypeDAL

from shared_code.data_model.mixins.effdt import setup_record_operators
from shared_code.data_model.tables import (
    AuthUser,
    CountsPerMinute,
    DynamicFilter,
    DynamicSort,
    Evidence,
    ImporterRun,
    ImporterRunCountStat,
    ImporterRunErrorStat,
    Method,
    MethodEd,
    Organisation,
    OrganisationEd,
    Product,
    ProductEd,
    SearchRankWeight,
    Signal,
    StaticContent,
    Supplier,
    SupplierEd,
    Tagged,
    TaggedEd,
    Vision,
    VisionEd,
)


def define_tables(db: TypeDAL) -> TypeDAL:
    """Define shared data-model tables in the provided database."""
    db.define(
        AuthUser,
        rname="auth_user",
        format="%(email)s",
        singular="User",
        plural="Users",
        redefine=True,
        migrate=False,
    )

    # influences UI:
    AuthUser.reorder_fields(
        AuthUser.id,
        AuthUser.first_name,
        AuthUser.last_name,
        AuthUser.email,
        AuthUser.password,
        AuthUser.onderwijs_rol,
        AuthUser.onderwijs_rol_anders,
        AuthUser.onderwijs_sector,
        # ... other internal fields, not shown to user ...
    )

    db.define(
        Evidence,
        rname="evidence",
        format="%(gid)s",
        singular="Evidence",
        plural="Evidence",
        redefine=True,
        migrate=False,
    )
    db.define(
        Signal,
        rname="signal",
        format="%(name)s",
        singular="Signal",
        plural="Signals",
        redefine=True,
        migrate=False,
    )

    db.define(
        CountsPerMinute,
        rname="counts_per_minute",
        format="%(name)s",
        singular="CountsPerMinute",
        plural="CountsPerMinute",
        redefine=True,
        migrate=False,
    )

    db.define(
        DynamicSort,
        rname="dynamic_sort",
        format="%(slug)s",
        singular="DynamicSort",
        plural="DynamicSorts",
        redefine=True,
        migrate=False,
    )

    db.define(
        SearchRankWeight,
        rname="search_rank_weight",
        format="%(entity_kind)s#%(key)s",
        singular="SearchRankWeight",
        plural="SearchRankWeights",
        redefine=True,
        migrate=False,
    )

    db.define(
        StaticContent,
        rname="static_content",
        format="%(scope)s#%(section)s",
        singular="StaticContent",
        plural="StaticContents",
        redefine=True,
        migrate=False,
    )

    db.define(
        Tagged,
        rname="tagged_model",
        format="%(predicate)s",
        singular="Tagged",
        plural="Tagged",
        redefine=True,
        migrate=False,
        permissions={"insert": False},
    )
    db.define(
        TaggedEd,
        rname="tagged_ed",
        format="%(predicate)s",
        singular="TaggedEd",
        plural="TaggedEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        Organisation,
        rname="organisation_model",
        format="%(name)s",
        singular="Organisation",
        plural="Organisations",
        redefine=True,
        migrate=False,
        permissions={"insert": False},
    )
    db.define(
        OrganisationEd,
        rname="organisation_ed",
        format="%(name)s",
        singular="OrganisationEd",
        plural="OrganisationEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        Supplier,
        rname="supplier_model",
        format="%(name)s",
        singular="Supplier",
        plural="Suppliers",
        redefine=True,
        migrate=False,
        permissions={"insert": False},
    )
    db.define(
        SupplierEd,
        rname="supplier_ed",
        format="%(name)s",
        singular="SupplierEd",
        plural="SupplierEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        Method,
        rname="method_model",
        format="%(name)s",
        singular="Method",
        plural="Methods",
        redefine=True,
        migrate=False,
        permissions={"insert": False},
    )
    db.define(
        MethodEd,
        rname="method_ed",
        format="%(name)s",
        singular="MethodEd",
        plural="MethodEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        Product,
        rname="product_model",
        format="%(name)s",
        singular="Product",
        plural="Products",
        redefine=True,
        migrate=False,
        permissions={"insert": False},
    )
    db.define(
        ProductEd,
        rname="product_ed",
        format="%(name)s",
        singular="ProductEd",
        plural="ProductEds",
        redefine=True,
        migrate=False,
    )

    db.define(
        DynamicFilter,
        rname="dynamic_filter",
        format="%(slug)s",
        singular="DynamicFilter",
        plural="DynamicFilters",
        redefine=True,
        migrate=False,
    )

    db.define(
        Vision,
        rname="vision_model",
        format="%(olid)s",
        singular="Vision",
        plural="Visions",
        redefine=True,
        migrate=False,
        permissions={"insert": False},
    )
    db.define(
        VisionEd,
        rname="vision_ed",
        format="%(olid)s",
        singular="VisionEd",
        plural="VisionEds",
        redefine=True,
        migrate=False,
    )

    db.define(
        ImporterRun,
        rname="importer_run",
        format="%(source)s",
        singular="ImporterRun",
        plural="ImporterRuns",
        redefine=True,
        migrate=False,
    )
    db.define(
        ImporterRunCountStat,
        rname="importer_run_count_stat",
        format="%(metric)s",
        singular="ImporterRunCountStat",
        plural="ImporterRunCountStats",
        redefine=True,
        migrate=False,
    )
    db.define(
        ImporterRunErrorStat,
        rname="importer_run_error_stat",
        format="%(error_code)s",
        singular="ImporterRunErrorStat",
        plural="ImporterRunErrorStats",
        redefine=True,
        migrate=False,
    )

    setup_record_operators(db=db)

    # prevent locks:
    db.commit()
    return db
