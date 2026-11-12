"""Browser coverage for catalogue filter option paging and filter-key validation."""

import html
import re
import uuid

from playwright.sync_api import Page, expect

from .auth_helpers import BrowserDataLoader, _create_verified_user, _login_as_user
from .settings import BASE_URL

OPTION_PAGE_SIZE = 5


def test_more_options_stay_limited_to_the_product_tab(page: Page, seed_browser_data: BrowserDataLoader) -> None:
    """Later option pages of a product-tab filter use the tab-scoped endpoint, like the first page."""
    data = seed_browser_data(page, "catalog")
    created = page.request.post(f"{BASE_URL}/test_catalog_filter")
    assert created.ok, created.text()
    catalog_filter = created.json()

    try:
        first_page = page.request.get(
            f"{BASE_URL}/htmx/catalog-filter-options/product/{catalog_filter['slug']}",
            params={"q": data["search_term"], "offset": 0, "limit": OPTION_PAGE_SIZE},
        )
        assert first_page.ok, first_page.text()

        match = re.search(r'hx-get="([^"]+)"', first_page.text())
        assert match, "Expected a 'Meer opties laden' trigger for twenty matching products"
        next_url = html.unescape(match.group(1))
        assert next_url.startswith(f"/htmx/catalog-filter-options/product/{catalog_filter['slug']}?")

        second_page = page.request.get(f"{BASE_URL}{next_url}")
        assert second_page.ok, second_page.text()
        expected = data["material_names"][OPTION_PAGE_SIZE : OPTION_PAGE_SIZE * 2]
        assert re.findall(r'<span class="item-label">([^<]+)</span>', second_page.text()) == expected
    finally:
        removed = page.request.post(f"{BASE_URL}/test_catalog_filter/{catalog_filter['gid']}/delete")
        assert removed.ok, removed.text()


def create_inactive_filter(page: Page, slug: str, applies_to: str) -> None:
    """Submit the admin filter form without activating the filter in the public catalogue."""
    page.goto(f"{BASE_URL}/admin/dynamic-filters/new")
    page.fill("input[name='slug']", slug)
    page.fill("input[name='label']", f"Filter {slug}")
    page.select_option("select[name='applies_to']", applies_to)
    page.select_option("select[name='widget_kind']", "search")
    page.uncheck("input[name='is_active']")
    page.locator("button[type='submit'], input[type='submit']").first.click()


def test_filter_keys_must_be_unique_within_overlapping_catalogue_tabs(page: Page) -> None:
    """A product filter cannot reuse a key that already applies to products and methods; packages may."""
    email, password = _create_verified_user(page, prefix="filter-keys", admin=True)
    _login_as_user(page, email=email, password=password)
    slug = f"key-{uuid.uuid4().hex[:12]}"
    # The form repeats its errors in a flash alert; check the error attached to the slug field itself.
    conflict = page.locator(".py4web-validation-error", has_text="overlappend catalogusonderdeel")

    create_inactive_filter(page, slug, applies_to="both")
    expect(page.locator(".grid-table tr", has_text=slug)).to_have_count(1)

    create_inactive_filter(page, slug, applies_to="product")
    expect(conflict).to_be_visible()

    create_inactive_filter(page, slug, applies_to="package")
    expect(conflict).to_have_count(0)
    expect(page.locator(".grid-table tr", has_text=slug)).to_have_count(2)
