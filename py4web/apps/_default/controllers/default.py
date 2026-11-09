import json
import typing as t
from pathlib import Path
from uuid import UUID

from common.controllers.error import FancyHTTP
from common.fixtures.content_editable import ContentEditableV2
from common.models.request_data import CatalogRequest
from typedal import PaginatedRows
from yatl.helpers import XML

from py4web import URL, action, redirect, request, response
from shared_code.data_model import AnyDict, Method, Product, TimelineEvent
from shared_code.modules.catalog_filters import InvalidCatalogFilterValue, ResolvedCatalogFilters
from shared_code.util.html import catalog_external_url
from shared_code.util.lists import uniq

from ..fixtures import common
from ..models import auth, backend, db
from ..models.catalog_presentation import (
    catalog_fields,
    catalog_report_url,
    comparison_link_label,
    display_catalog_value,
    display_vision_properties,
)
from ..models.favorites import (
    FavoriteActionContext,
    FavoriteRowsContext,
    favorite_action_context,
    favorite_rows_context,
    recent_favorites,
)
from ..models.settings import (
    MethodCatalogSettings,
    MethodFavoriteSettings,
    ProductCatalogSettings,
    ProductFavoriteSettings,
)
from ..models.timeline import event_summary, timeline_context

method_request = MethodCatalogSettings()
product_request = ProductCatalogSettings()
method_favorite_settings = MethodFavoriteSettings()
product_favorite_settings = ProductFavoriteSettings()


def faq_answer_text(question: AnyDict) -> str:
    """Flatten one structured FAQ answer for search and metadata."""
    return "\n\n".join(block["text"] if block["type"] == "p" else "\n".join(block["items"]) for block in question["a"])


class CatalogResultsContext(t.TypedDict):
    """Template values shared by full catalogue pages and HTMX result swaps."""

    resolved_filters: ResolvedCatalogFilters
    selected_sort: str
    active_filter_count: int
    rows: PaginatedRows[Method] | PaginatedRows[Product]
    view_mode: str
    display_catalog_value: t.Callable[..., t.Any]


@action("index")
@common("index.html")
def index() -> AnyDict:
    """Render the public Open Keuzecatalogus landing page."""
    events = TimelineEvent.all()
    return {"timeline": timeline_context(events), "event_summary": event_summary}


@action("privacyverklaring")
@common("privacyverklaring.html")
def privacyverklaring() -> AnyDict:
    """Render the public privacy statement."""
    return {}


@action("faq")
@action("faq.html")
@common("faq.html")
def faq() -> AnyDict:
    """Render the public frequently asked questions page."""
    faq_data = json.loads(Path("/data/seeding/faq.json").read_text(encoding="utf-8"))
    questions = [question for category in faq_data["categories"] for question in category["questions"]]
    for question in questions:
        question["search_text"] = f"{question['q']} {faq_answer_text(question)}".lower()
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "@id": "https://openkeuzecatalogus.nl/faq#faqpage",
        "url": "https://openkeuzecatalogus.nl/faq",
        "inLanguage": "nl-NL",
        "mainEntity": [
            {
                "@type": "Question",
                "name": question["q"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": faq_answer_text(question),
                },
            }
            for question in questions
        ],
    }
    return {
        "faq_data": faq_data,
        "faq_schema": XML(json.dumps(schema, ensure_ascii=False).replace("<", r"\u003c")),
    }


@action("data/discussion-descriptions.json")
@action.uses(db)
def discussion_descriptions() -> AnyDict:
    """Return current modal descriptions for the landing-page timeline."""
    events = TimelineEvent.all()
    return {str(event.id): event.description or "" for event in events}


@action("auth/error")
@common("account_access.html")
def auth_no_roles() -> AnyDict:
    return {}


@action("methodes")
@common(ContentEditableV2("method_overview.html"), method_request)
def methods() -> AnyDict:
    return {
        "title": "Methodenoverzicht",
        **method_results_context(),
    }


@action("producten")
@common(ContentEditableV2("product_overview.html"), product_request)
def products() -> AnyDict:
    return {
        "title": "Productoverzicht",
        **product_results_context(),
    }


@action("product/<gid>")
@common("catalog_detail.html")
def product_detail(gid: str) -> AnyDict:
    """Show one available public product."""
    detail = backend.products.get_public_product_detail(
        gid, referer=request.headers.get("Referer"), from_similar=request.query.get("source") == "similar"
    )
    if detail is None:
        raise FancyHTTP(404, "Product niet gevonden")
    name = detail["product"].get("name") or "Onbekend product"

    return {
        "title": name,
        "heading": name,
        "back_url": URL("producten"),
        "back_label": "Terug naar producten",
        "catalog_external_url": catalog_external_url,
        "favorite_url": URL("htmx/favorieten", "product", gid) if auth.get_user() else None,
        "favorite_login_url": URL("auth/login", vars={"next": URL("product", gid)}, use_appname=False),
        "entity_kind": "product",
        "detail": detail,
        "similar_items": backend.similar_materials.for_product(detail["product"]),
        "catalog_fields": catalog_fields,
        "catalog_report_url": catalog_report_url,
        "display_catalog_value": display_catalog_value,
    }


@action("method/<gid>")
def method_redirect(gid: str) -> None:
    """Redirect the alternative method URL to the proper method detail route."""
    return redirect(URL("methode", gid))


@action("methode/<gid>")
@common("catalog_detail.html")
def method_detail(gid: str) -> AnyDict:
    """Show one available public method."""
    detail = backend.methods.get_public_method_detail(
        gid, referer=request.headers.get("Referer"), from_similar=request.query.get("source") == "similar"
    )
    if detail is None:
        raise FancyHTTP(404, "Methode niet gevonden")
    name = detail["method"].get("name") or "Onbekende methode"

    return {
        "title": name,
        "heading": name,
        "back_url": URL("methodes"),
        "back_label": "Terug naar methodes",
        "catalog_external_url": catalog_external_url,
        "favorite_url": URL("htmx/favorieten", "method", gid) if auth.get_user() else None,
        "favorite_login_url": URL("auth/login", vars={"next": URL("methode", gid)}, use_appname=False),
        "entity_kind": "method",
        "detail": detail,
        "similar_items": backend.similar_materials.for_method(detail["method"]),
        "catalog_fields": catalog_fields,
        "catalog_report_url": catalog_report_url,
        "display_catalog_value": display_catalog_value,
    }


@action("compare/<entity_kind>/<gids_path:path>")
@common("compare.html")
def compare(entity_kind: str, gids_path: str) -> AnyDict:
    """Show the selected public methods or products in URL order."""
    if entity_kind == "methode":
        return redirect(URL("compare", "method", gids_path))
    if entity_kind not in {"method", "product"}:
        raise FancyHTTP(404, "Onbekend vergelijkingstype")

    try:
        # split path by / ; canonize ; deduplicate
        validated_gids = gids_path.split("/")
        validated_gids = (str(UUID(gid.strip())) for gid in validated_gids)
        validated_gids = uniq(validated_gids)
    except ValueError as exc:
        raise FancyHTTP(404, "Ongeldige vergelijking") from exc

    if len(validated_gids) < 2:
        raise FancyHTTP(400, "Kies minstens twee items om te vergelijken")

    comparison = backend.comparison.load_public_comparison(entity_kind, validated_gids)

    return {
        "title": "Methodes vergelijken" if entity_kind == "method" else "Producten vergelijken",
        "entity_kind": entity_kind,
        "catalog_entity_kind": entity_kind,
        "display_catalog_value": display_catalog_value,
        "display_vision_properties": display_vision_properties,
        "comparison_link_label": comparison_link_label,
        **comparison,
    }


@action("htmx/methods/filters")
@common("htmx_method_filters.html", method_request)
def htmx_method_filters() -> AnyDict:
    resolved_filters = method_request.resolved_filters()
    return {
        "resolved_filters": resolved_filters,
        "selected_sort": method_request.selected_sort(resolved_filters),
    }


@action("htmx/methods/results")
@common("htmx_method_results.html", method_request)
def htmx_method_results() -> CatalogResultsContext:
    return method_results_context()


def method_results_context() -> CatalogResultsContext:
    """Render the same results for an overview and subsequent filter requests."""
    resolved_filters = method_request.resolved_filters()
    selected_sort = method_request.selected_sort(resolved_filters)

    try:
        rows = backend.methods.list_public_methods(
            resolved_filters,
            sort=selected_sort,
            page=method_request.page,
            limit=method_request.page_limit,
        )
    except InvalidCatalogFilterValue as exc:
        raise FancyHTTP(400, str(exc)) from exc

    return {
        "resolved_filters": resolved_filters,
        "selected_sort": selected_sort,
        "active_filter_count": resolved_filters.active_filter_count,
        "rows": rows,
        "view_mode": method_request.view,
        "display_catalog_value": display_catalog_value,
    }


@action("htmx/products/filters")
@common("htmx_product_filters.html", product_request)
def htmx_product_filters() -> AnyDict:
    resolved_filters = product_request.resolved_filters()

    return {
        "resolved_filters": resolved_filters,
        "selected_sort": product_request.selected_sort(resolved_filters),
    }


@action("htmx/products/results")
@common("htmx_product_results.html", product_request)
def htmx_product_results() -> CatalogResultsContext:
    return product_results_context()


@action("htmx/filter-options/<entity_kind>/<slug>")
@common("htmx_filter_options.html")
def catalog_filter_options(entity_kind: str, slug: str) -> AnyDict:
    """Search and page options for a large public catalogue filter."""
    params = CatalogRequest.from_request(request).filters
    if entity_kind == "method":
        resolved = backend.methods.resolve_public_method_filters(params)
    elif entity_kind == "product":
        resolved = backend.products.resolve_public_product_filters(params)
    else:
        raise FancyHTTP(404, "Onbekend filtertype")

    try:
        offset = max(0, int(request.query.get("offset", 0)))
        limit = min(100, max(1, int(request.query.get("limit", 100))))
    except (TypeError, ValueError) as exc:
        raise FancyHTTP(400, "Ongeldige paginering") from exc

    query = str(request.query.get("q", ""))
    try:
        page = resolved.option_page(slug, query=query, offset=offset, limit=limit)
    except KeyError as exc:
        raise FancyHTTP(404, "Onbekend filter") from exc
    return {
        "options": page.options,
        "selected_options": page.selected_options,
        "entity_kind": entity_kind,
        "slug": slug,
        "input_type": "checkbox" if page.definition.widget_kind == "multi-select" else "radio",
        "query": query,
        "limit": limit,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
    }


def product_results_context() -> CatalogResultsContext:
    """Render the same results for an overview and subsequent filter requests."""
    resolved_filters = product_request.resolved_filters()
    selected_sort = product_request.selected_sort(resolved_filters)

    try:
        rows = backend.products.list_public_products(
            resolved_filters,
            sort=selected_sort,
            page=product_request.page,
            limit=product_request.page_limit,
        )
    except InvalidCatalogFilterValue as exc:
        raise FancyHTTP(400, str(exc)) from exc

    return {
        "resolved_filters": resolved_filters,
        "selected_sort": selected_sort,
        "active_filter_count": resolved_filters.active_filter_count,
        "rows": rows,
        "view_mode": product_request.view,
        "display_catalog_value": display_catalog_value,
    }


@action("favorieten")
@common("favorites.html", auth.requires_login())
def favorites() -> AnyDict:
    """Show the authenticated user's product and method favorites."""
    return {"title": "Mijn favorieten"}


@action("htmx/favorieten/recent")
@common("components/favorite_recent.html", auth.requires_login())
def htmx_recent_favorites() -> AnyDict:
    """Render the compact profile-adjacent favorites list."""
    return {"items": recent_favorites()}


@action("htmx/favorieten/product")
@common("components/favorite_rows.html", auth.requires_login(), product_favorite_settings)
def htmx_product_favorites() -> FavoriteRowsContext:
    """Render one typed page of product favorites."""
    return favorite_rows_context(product_favorite_settings)


@action("htmx/favorieten/method")
@common("components/favorite_rows.html", auth.requires_login(), method_favorite_settings)
def htmx_method_favorites() -> FavoriteRowsContext:
    """Render one typed page of method favorites."""
    return favorite_rows_context(method_favorite_settings)


@action("htmx/favorieten/product/<gid>", method="GET")
@common("components/favorite_action.html", auth.requires_login(), product_favorite_settings)
def htmx_product_favorite_action(gid: str) -> FavoriteActionContext:
    """Render the favorite control for one public product."""
    return favorite_action_context(product_favorite_settings, gid)


@action("htmx/favorieten/method/<gid>", method="GET")
@common("components/favorite_action.html", auth.requires_login(), method_favorite_settings)
def htmx_method_favorite_action(gid: str) -> FavoriteActionContext:
    """Render the favorite control for one public method."""
    return favorite_action_context(method_favorite_settings, gid)


def _set_favorite(settings: ProductFavoriteSettings | MethodFavoriteSettings, gid: str) -> None:
    """Set one favorite and translate invalid client input into an HTTP response."""
    try:
        backend.favorites.set_favorite(settings.entity_kind, gid, settings.requested_active)
    except ValueError as exc:
        raise FancyHTTP(400, str(exc)) from exc
    response.headers["HX-Trigger"] = "ew:favorites_changed"


@action("htmx/favorieten/product/<gid>", method="POST")
@common(auth.requires_login(), product_favorite_settings)
def htmx_set_product_favorite(gid: str) -> None:
    """Set the authenticated user's product favorite state."""
    _set_favorite(product_favorite_settings, gid)


@action("htmx/favorieten/method/<gid>", method="POST")
@common(auth.requires_login(), method_favorite_settings)
def htmx_set_method_favorite(gid: str) -> None:
    """Set the authenticated user's method favorite state."""
    _set_favorite(method_favorite_settings, gid)
