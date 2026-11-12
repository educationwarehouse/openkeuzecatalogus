"""Loading states stay readable and do not move existing catalogue results."""

import pytest
from playwright.sync_api import Page, Route, expect

from .settings import BASE_URL


@pytest.mark.parametrize("path", ["producten", "pakketten"])
def test_catalog_loading_preserves_geometry_and_announces_status(page: Page, path: str) -> None:
    """Keep existing results stable while announcing catalogue updates."""
    pending: list[Route] = []

    def hold_request(route: Route) -> None:
        pending.append(route)

    page.route("**/htmx/**", hold_request)
    page.goto(f"{BASE_URL}/{path}?view=list")
    skeletons = page.locator(".okl-skeleton")
    expect(skeletons).to_have_count(1)
    expect(page.locator(".okl-catalog-results h2")).to_be_visible()
    for width in (320, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for request in pending:
        request.continue_()
    page.unroute("**/htmx/**")
    pending.clear()
    expect(skeletons).to_have_count(0)
    results = page.locator(".okl-catalog-results")
    heading = results.locator("h2")
    expect(heading).to_be_visible()
    expect(page.locator(".htmx-request")).to_have_count(0)
    page.route("**/htmx/**/results*", hold_request)
    before = heading.bounding_box()
    page.get_by_role("button", name="Tegels", exact=True).click()
    expect(results).to_have_attribute("aria-busy", "true")
    expect(results.get_by_role("status")).to_have_text("Resultaten bijwerken…")
    assert heading.bounding_box() == before
    for request in pending:
        request.continue_()
    page.unroute("**/htmx/**/results*")
    expect(results).to_have_attribute("aria-busy", "false")
    expect(results.locator(".catalog-results-feedback")).to_have_count(0)


@pytest.mark.parametrize("reduced_motion", ["reduce", "no-preference"])
def test_loading_bar_stays_steady_across_navigation_and_followup_requests(page: Page, reduced_motion: str) -> None:
    """Reuse one stable loading indicator for navigation and filtering."""
    page.emulate_media(reduced_motion=reduced_motion)
    page.goto(f"{BASE_URL}/index")
    progress = page.get_by_role("progressbar", name="Pagina laden", include_hidden=True)
    expect(progress).to_be_hidden()
    page.evaluate("""() => {
        window.originalLoadingIndicator = document.querySelector('.okl-navigation-progress');
        window.loadingVisibility = [];
        new MutationObserver(() => {
            window.loadingVisibility.push({hidden: window.originalLoadingIndicator.hidden, time: performance.now()});
        }).observe(window.originalLoadingIndicator, {attributes: true, attributeFilter: ['hidden']});
    }""")
    pending: list[Route] = []

    def hold_request(route: Route) -> None:
        pending.append(route)

    page.route("**/producten", hold_request)
    page.route("**/htmx/**", hold_request)
    page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Catalogus", exact=True).click()
    expect(progress).to_be_visible()
    before = progress.bounding_box()
    page.wait_for_timeout(250)
    assert progress.bounding_box() == before
    assert progress.evaluate("element => element.getAnimations().length === 0")
    pending.pop(0).continue_()
    page.unroute("**/producten")
    expect(page.locator("main h1")).to_be_focused()
    expect(page.locator(".okl-catalog-results h2")).to_be_visible()
    expect(page.locator(".okl-skeleton")).to_have_count(1)
    assert page.evaluate("window.originalLoadingIndicator === document.querySelector('.okl-navigation-progress')")
    for request in pending:
        request.continue_()
    page.unroute("**/htmx/**")
    expect(page.locator(".okl-skeleton")).to_have_count(0)
    expect(progress).to_be_hidden()

    pending.clear()
    page.route("**/htmx/**/results*", hold_request)
    page.get_by_role("group", name="Weergave wisselen").locator('button[aria-pressed="false"]').click()
    expect(progress).to_be_visible()
    for request in pending:
        request.continue_()
    page.unroute("**/htmx/**/results*")
    expect(progress).to_be_hidden()
    visibility = page.evaluate("window.loadingVisibility")
    assert visibility[-1]["time"] - visibility[-2]["time"] >= 390
