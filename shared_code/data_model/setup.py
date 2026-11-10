"""Database table setup entrypoint for shared data models."""

from __future__ import annotations

import typing as t

from typedal.types import Permissions

from shared_code.data_model.mixins.effdt import setup_record_operators
from shared_code.data_model.tables import (
    AuthUser,
    CatalogFavorite,
    CatalogFavoriteEd,
    CatalogusSetting,
    CountsPerMinute,
    DecisionMaterialSelection,
    DecisionProcess,
    DecisionProcessNote,
    DecisionProcessNoteEd,
    DecisionProsAndCons,
    DecisionTeam,
    DecisionTeamEd,
    DecisionThemeVision,
    DynamicFilter,
    DynamicFilterEd,
    DynamicSort,
    DynamicSortEd,
    Evidence,
    FaqQuestion,
    FaqSection,
    Identity,
    ImporterRun,
    ImporterRunEvent,
    LearningMaterial,
    LLMConfiguration,
    LLMPlaygroundScenario,
    LLMPrompt,
    LocationProductUsageReport,
    Membership,
    Method,
    MethodEd,
    Organisation,
    OrganisationEd,
    Product,
    ProductEd,
    RecursiveMembers,
    SearchRankWeight,
    SearchRankWeightEd,
    Signal,
    StaticContent,
    Supplier,
    SupplierEd,
    Tagged,
    TaggedEd,
    TimelineEvent,
    Vision,
    VisionEd,
    VisionThemeDefinition,
    VisionThemeDefinitionEd,
)

if t.TYPE_CHECKING:
    from shared_code.infra.database import DatabaseContext
    from shared_code.services.caching import CacheService

PERMISSION_READONLY: Permissions = {
    "read": True,
    "insert": False,
    "update": False,
    "delete": False,
}

PERMISSION_MODEL_VIEW: Permissions = {
    "read": True,
    "insert": False,
    # delegated to _ed via RecordOperators:
    "update": True,
    "delete": True,
}


def define_tables(db: DatabaseContext, caching: CacheService | None = None) -> DatabaseContext:
    """Define shared data-model tables in the provided database."""
    from shared_code.services.caching.writes import install_write_invalidation

    db.define(
        AuthUser,
        rname="auth_user",
        format="%(email)s",
        singular="User",
        plural="Users",
        redefine=True,
        migrate=False,
    )

    db.define(
        CatalogFavorite,
        rname="catalog_favorite_model",
        format="%(entity_kind)s#%(entity_gid)s",
        singular="Favoriet",
        plural="Favorieten",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_READONLY,
    )
    db.define(
        CatalogFavoriteEd,
        rname="catalog_favorite_ed",
        format="%(entity_kind)s#%(entity_gid)s",
        singular="Favoriet versie",
        plural="Favoriet versies",
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
        rname="dynamic_sort_model",
        format="%(slug)s",
        singular="DynamicSort",
        plural="DynamicSorts",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_MODEL_VIEW,
    )
    db.define(
        DynamicSortEd,
        rname="dynamic_sort_ed",
        format="%(slug)s",
        singular="DynamicSortEd",
        plural="DynamicSortEds",
        redefine=True,
        migrate=False,
    )

    db.define(
        SearchRankWeight,
        rname="search_rank_weight_model",
        format="%(entity_kind)s#%(key)s",
        singular="SearchRankWeight",
        plural="SearchRankWeights",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_MODEL_VIEW,
    )
    db.define(
        SearchRankWeightEd,
        rname="search_rank_weight_ed",
        format="%(entity_kind)s#%(key)s",
        singular="SearchRankWeightEd",
        plural="SearchRankWeightEds",
        redefine=True,
        migrate=False,
    )

    db.define(
        CatalogusSetting,
        rname="catalogus_setting",
        format="%(key)s",
        singular="Catalogusinstelling",
        plural="Catalogusinstellingen",
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
        TimelineEvent,
        rname="timeline_event",
        format="%(title)s",
        singular="Tijdlijngebeurtenis",
        plural="Tijdlijngebeurtenissen",
        redefine=True,
        migrate=False,
    )
    db.define(
        FaqSection,
        rname="faq_section",
        format="%(title)s",
        singular="FAQ-sectie",
        plural="FAQ-secties",
        redefine=True,
        migrate=False,
    )
    db.define(
        FaqQuestion,
        rname="faq_question",
        format="%(question)s",
        singular="FAQ-vraag",
        plural="FAQ-vragen",
        redefine=True,
        migrate=False,
    )

    db.define(LLMPrompt, rname="llm_prompt", redefine=True, migrate=False)
    db.define(LLMConfiguration, rname="llm_configuration", redefine=True, migrate=False)
    db.define(LLMPlaygroundScenario, rname="llm_playground_scenario", redefine=True, migrate=False)

    db.define(
        Tagged,
        rname="tagged_model",
        format="%(predicate)s",
        singular="Tagged",
        plural="Tagged",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_MODEL_VIEW,
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
        permissions=PERMISSION_MODEL_VIEW,
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
        permissions=PERMISSION_MODEL_VIEW,
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
        permissions=PERMISSION_MODEL_VIEW,
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
        permissions=PERMISSION_MODEL_VIEW,
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
        rname="dynamic_filter_model",
        format="%(slug)s",
        singular="DynamicFilter",
        plural="DynamicFilters",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_MODEL_VIEW,
    )
    db.define(
        DynamicFilterEd,
        rname="dynamic_filter_ed",
        format="%(slug)s",
        singular="DynamicFilterEd",
        plural="DynamicFilterEds",
        redefine=True,
        migrate=False,
    )

    db.define(
        VisionThemeDefinition,
        rname="vision_theme_definition_model",
        format="%(title)s",
        singular="Visie-thema-definitie",
        plural="Visie-thema-definities",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_MODEL_VIEW,
    )
    db.define(
        VisionThemeDefinitionEd,
        rname="vision_theme_definition_ed",
        format="%(title)s",
        singular="Visie-thema-definitie",
        plural="Visie-thema-definities",
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
        permissions=PERMISSION_MODEL_VIEW,
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
        singular="Importrun",
        plural="Importruns",
        redefine=True,
        migrate=False,
        # permissions=PERMISSION_READONLY,
    )
    db.define(
        ImporterRunEvent,
        rname="importer_run_event",
        format="%(metric)s",
        singular="Gebeurtenis in importrun",
        plural="Gebeurtenissen in importrun",
        redefine=True,
        migrate=False,
        # permissions=PERMISSION_READONLY,
    )

    # kc

    db.define(
        DecisionTeam,
        rname="decision_team_model",
        format="%(name)s",
        singular="Vakgroep",
        plural="Vakgroepen",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_MODEL_VIEW,
    )
    db.define(
        DecisionTeamEd,
        rname="decision_team_ed",
        format="%(name)s",
        singular="DecisionTeamEd",
        plural="DecisionTeamEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        DecisionProcess,
        rname="decision_process",
        format="%(schoolyear)s",
        singular="Keuzeproces",
        plural="Keuzeprocessen",
        redefine=True,
        migrate=False,
    )
    db.define(
        DecisionProcessNote,
        rname="decision_process_note_model",
        format="%(theme)s",
        singular="Procesnotitie",
        plural="Procesnotities",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_MODEL_VIEW,
    )
    db.define(
        DecisionProcessNoteEd,
        rname="decision_process_note_ed",
        format="%(theme)s",
        singular="DecisionProcessNoteEd",
        plural="DecisionProcessNoteEds",
        redefine=True,
        migrate=False,
    )
    db.define(
        DecisionMaterialSelection,
        rname="decision_material_selection",
        format="%(name)s",
        singular="Geselecteerd leermiddel",
        plural="Geselecteerde leermiddelen",
        redefine=True,
        migrate=False,
    )
    db.define(
        DecisionProsAndCons,
        rname="decision_pros_and_cons",
        format="%(item_type)s",
        singular="Plus- of minpunt",
        plural="Plus- en minpunten",
        redefine=True,
        migrate=False,
    )
    db.define(
        DecisionThemeVision,
        rname="decision_theme_vision",
        format="%(theme)s",
        singular="Themavisie",
        plural="Themavisies",
        redefine=True,
        migrate=False,
    )
    db.define(
        LocationProductUsageReport,
        rname="location_product_usage_report_v1",
        format="%(product_name)s",
        singular="Productgebruik",
        plural="Productgebruik",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_READONLY,
    )
    db.define(
        LearningMaterial,
        rname="learning_material",
        format="%(name)s",
        singular="Leermiddel",
        plural="Leermiddelen",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_READONLY,
    )
    db.define(
        Identity,
        rname="identity",
        singular="Identiteit",
        plural="Identiteiten",
        redefine=True,
        migrate=False,
    )
    db.define(
        Membership,
        rname="membership",
        singular="Lidmaatschap",
        plural="Lidmaatschappen",
        redefine=True,
        migrate=False,
    )
    db.define(
        RecursiveMembers,
        rname="recursive_members",
        singular="Lid",
        plural="Leden",
        redefine=True,
        migrate=False,
        permissions=PERMISSION_READONLY,
    )

    setup_record_operators(db=db)

    if caching is None:
        caching = db.caching
    db.caching = caching
    for model in set(db._class_map.values()):
        table_name = str(model._table)
        if table_name.startswith("typedal_") or table_name in {"cache_entry", "cache_dependency"}:
            continue
        install_write_invalidation(model, caching=caching)

    # prevent locks:
    db.commit()
    return db
