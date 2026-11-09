"""Completed public catalogues return from history without replaying their requests."""

import re

import pytest
from playwright.sync_api import Page, expect

from .auth_helpers import BrowserDataLoader
from .settings import BASE_URL


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("path", ["methodes", "producten"])
def test_catalog_history_restores_results_without_requests(
    page: Page, seed_browser_data: BrowserDataLoader, width: int, path: str
) -> None:
    """Restore catalogue state, focus and scroll without replaying requests."""
    page.set_viewport_size({"width": width, "height": 844})
    data = seed_browser_data(page, scenario="catalog")
    page.goto(f"{BASE_URL}/auth/logout")
    page.goto(f"{BASE_URL}/{path}")
    expect(page.locator(".okl-catalog-results h2")).to_be_visible()
    expect(page.locator("#catalog-filters .okl-skeleton")).to_have_count(0)
    if width < 992:
        page.get_by_role("button", name=re.compile("Filters tonen")).click()
    search = page.get_by_role("searchbox", name="Zoekterm", exact=True)
    with page.expect_response(lambda response: "/results" in response.url):
        search.fill(data["search_term"])
    expect(page).to_have_url(re.compile(f"q={data['search_term']}"))
    expect(page.locator(".okl-catalog-page")).to_have_attribute("data-okl-history-ready", "true")
    cards = page.locator(".catalog-result-item")
    expect(cards).to_have_count(20)
    card = cards.nth(10)
    card.locator("summary").click()
    link = card.locator(".okl-catalog-card__view")
    detail_name = data["material_names"][10]
    link.scroll_into_view_if_needed()
    overview_url = page.url
    page.evaluate("""window.catalogDocument = true;
        document.addEventListener('htmx:beforeRequest', event => {
            if (event.detail.requestConfig.boosted) window.departureScroll = scrollY;
        });""")
    link.click()
    expect(page.locator("main h1")).to_have_text(detail_name)
    scroll = page.evaluate("window.departureScroll")

    requests = []
    page.on("request", lambda request: requests.append(request.url))
    for _ in range(2):
        requests.clear()
        page.go_back()
        expect(page).to_have_url(overview_url)
        expect(page.locator(".catalog-result-item")).to_have_count(20)
        expect(link).to_be_focused()
        expect(search).to_have_value(data["search_term"])
        expect(page.locator(".catalog-result-item").nth(10).locator("details")).to_have_attribute("open", "")
        expect(page.locator(".okl-skeleton")).to_have_count(0)
        expect(page.get_by_role("progressbar", name="Pagina laden", include_hidden=True)).to_be_hidden()
        assert abs(page.evaluate("scrollY") - scroll) <= 2
        assert page.evaluate("window.catalogDocument") is True
        page.wait_for_timeout(500)
        assert abs(page.evaluate("scrollY") - scroll) <= 2
        assert not any("/htmx/" in url or url == overview_url for url in requests), requests
        page.go_forward()
        expect(page.locator("main h1")).to_have_text(detail_name)

    page.go_back()
    expect(link).to_be_focused()
    if width < 992 and not search.is_visible():
        page.get_by_role("button", name=re.compile("Filters tonen")).click()
    sort = page.get_by_role("button", name="Sorteren op: Alfabetisch (A-Z)", exact=True)
    sort.press("ArrowDown")
    page.get_by_role("option", name="Alfabetisch (Z-A)", exact=True).press("Enter")
    expect(page).to_have_url(re.compile("sort=name_desc"))
    expect(page.locator(".okl-catalog-page")).to_have_attribute("data-okl-history-ready", "true")
    assert page.evaluate(
        """path => JSON.parse(sessionStorage.getItem('htmx-history-cache'))
            .every(item => new URL(item.url, location.origin).pathname === '/' + path)""",
        path,
    )
    page.reload()
    if width < 992:
        page.get_by_role("button", name=re.compile("Filters tonen")).click()
    search.fill(f"{data['search_term']} -{data['search_term']}")
    expect(page.locator(".catalog-result-item")).to_have_count(0)
    expect(page.get_by_role("heading", name=f"Geen {path} gevonden")).to_be_visible()
    assert page.evaluate("sessionStorage.getItem('htmx-history-cache')") is None


def test_history_without_browser_storage_uses_server(page: Page) -> None:
    """Fall back to a server request when session storage is unavailable."""
    page.add_init_script("""Object.defineProperty(window, 'sessionStorage', {
        get() { throw new DOMException('Storage disabled', 'SecurityError'); }
    });""")
    page.goto(f"{BASE_URL}/methodes")
    expect(page.locator("#method-results h2")).to_be_visible()
    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Home", exact=True).click()
    expect(page.locator("main h1")).to_contain_text("Vind leermiddelen")
    page.go_back()
    expect(page.locator("main h1")).to_have_text("Methodes & Producten")
    expect(page.locator("#method-results h2")).to_be_visible()
