import typing as t

from common.models.request_data import CatalogRequest

from py4web import HTTP, URL, action, redirect, request
from shared_code.modules.catalog_filters import InvalidCatalogFilterValue

from ..fixtures import common
from ..models import auth, backend


@action("index")
@common()
def index() -> None:
    return redirect(URL("producten"))


@action("profile")
@common(None, auth.user)
def profile() -> str:
    me = auth.get_user()
    return str(me.as_dict() if me else {})


@action("auth/error")
@common()
def auth_no_roles() -> str:
    return "geen rollen (todo)"


@action("methodes")
@action.uses("method_overview.html")
@common()
def methods() -> dict[str, t.Any]:
    return {
        "title": "Methodenoverzicht",
    }


@action("producten")
@action.uses("product_overview.html")
@common()
def products() -> dict[str, t.Any]:
    return {
        "title": "Productoverzicht",
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
        raise HTTP(400, str(exc)) from exc

    return {
        "active_filter_count": resolved_filters.active_filter_count,
        "rows": rows,
        "view_mode": catalog_request.view,
    }
