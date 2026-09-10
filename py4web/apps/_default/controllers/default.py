import json
import typing as t
from uuid import UUID

from common.controllers.error import FancyHTTP
from common.models.request_data import CatalogRequest

from py4web import URL, action, redirect, request
from shared_code.modules.catalog_filters import InvalidCatalogFilterValue
from shared_code.util.lists import uniq

from ..fixtures import common
from ..fixtures.content_editable import ContentEditableV2
from ..models import backend


@action("index")
@common()
def index() -> None:
    return redirect(URL("producten"))


@action("auth/error")
@common()
def auth_no_roles() -> str:
    return "geen rollen (todo)"


@action("methodes")
@common(ContentEditableV2("method_overview.html"))
def methods() -> dict[str, t.Any]:
    return {
        "title": "Methodenoverzicht",
    }


@action("producten")
@common(ContentEditableV2("product_overview.html"))
def products() -> dict[str, t.Any]:
    return {
        "title": "Productoverzicht",
    }


@action("product/<gid>")
@action.uses("catalog_detail.html")
@common()
def product_detail(gid: str) -> dict[str, t.Any]:
    """Show one available public product."""
    detail = backend.products.get_public_product_detail(gid)
    if detail is None:
        raise FancyHTTP(404, "Product niet gevonden")

    return {
        "title": detail["product"].get("name") or "Product",
        "heading": detail["product"].get("name") or "Onbenoemd product",
        "back_url": URL("producten"),
        "back_label": "Terug naar producten",
        "payload_json": json.dumps(detail, ensure_ascii=False, indent=2, default=str),
    }


@action("methode/<gid>")
@action.uses("catalog_detail.html")
@common()
def method_detail(gid: str) -> dict[str, t.Any]:
    """Show one available public method."""
    detail = backend.methods.get_public_method_detail(gid)
    if detail is None:
        raise FancyHTTP(404, "Methode niet gevonden")

    return {
        "title": detail["method"].get("name") or "Methode",
        "heading": detail["method"].get("name") or "Onbenoemde methode",
        "back_url": URL("methodes"),
        "back_label": "Terug naar methodes",
        "payload_json": json.dumps(detail, ensure_ascii=False, indent=2, default=str),
    }


@action("compare/<entity_kind>/<gids_path:path>")
@action.uses("compare.html")
@common()
def compare(entity_kind: str, gids_path: str) -> dict[str, t.Any]:
    """Show the selected public methods or products in URL order."""
    if entity_kind not in {"methode", "product"}:
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

    comparison_entity_kind = "method" if entity_kind == "methode" else "product"
    comparison = backend.comparison.load_public_comparison(comparison_entity_kind, validated_gids)

    return {
        "title": "Methodes vergelijken" if entity_kind == "methode" else "Producten vergelijken",
        "entity_kind": entity_kind,
        **comparison,
    }


@action("htmx/methods/filters")
@action.uses("htmx_method_filters.html")
@common()
def htmx_method_filters() -> dict[str, t.Any]:
    catalog_request = CatalogRequest.from_request(request)
    resolved_filters = catalog_request.method_filters()
    return {
        "resolved_filters": resolved_filters,
    }


@action("htmx/methods/results")
@action.uses("htmx_method_results.html")
@common()
def htmx_method_results() -> dict[str, t.Any]:
    catalog_request = CatalogRequest.from_request(request)
    resolved_filters = catalog_request.method_filters()

    return {
        "active_filter_count": resolved_filters.active_filter_count,
        "rows": backend.methods.list_public_methods(
            resolved_filters,
            sort=catalog_request.sort,
            # todo: merge sort/page/limit by passing list_public_methods(catalog_request ? )
            page=catalog_request.page,
            limit=catalog_request.page_limit,
        ),
        "view_mode": catalog_request.view,
    }


@action("htmx/products/filters")
@action.uses("htmx_product_filters.html")
@common()
def htmx_product_filters() -> dict[str, t.Any]:
    catalog_request = CatalogRequest.from_request(request)
    resolved_filters = catalog_request.product_filters()

    return {
        "resolved_filters": resolved_filters,
    }


@action("htmx/products/results")
@action.uses("htmx_product_results.html")
@common()
def htmx_product_results() -> dict[str, t.Any]:
    catalog_request = CatalogRequest.from_request(request)
    resolved_filters = catalog_request.product_filters()

    try:
        rows = backend.products.list_public_products(
            resolved_filters,
            sort=catalog_request.sort,
            page=catalog_request.page,
            limit=catalog_request.page_limit,
        )
    except InvalidCatalogFilterValue as exc:
        raise FancyHTTP(400, str(exc)) from exc

    return {
        "active_filter_count": resolved_filters.active_filter_count,
        "rows": rows,
        "view_mode": catalog_request.view,
    }
