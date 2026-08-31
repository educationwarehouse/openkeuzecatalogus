"""Browser-level coverage for public catalogue endpoints."""

from playwright.sync_api import Page

from .conftest import BASE_URL


def test_product_results_rejects_invalid_budget_filter_with_client_error(page: Page) -> None:
    """A manually edited budget filter must not turn the HTMX endpoint into a 500."""
    response = page.request.get(
        f"{BASE_URL}/htmx/products/results",
        params={"bdgt": "abc-def"},
        headers={"HX-Request": "true"},
    )
    assert 400 <= response.status < 500
