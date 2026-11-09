"""Partial process updates keep reading position, focus and the archived filter."""

import pytest
from playwright.sync_api import Page, Route, expect

from .auth_helpers import BrowserDataLoader
from .settings import BASE_URL


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("archived", [False, True])
def test_archive_keeps_overview_position_and_focus(
    page: Page, seed_browser_data: BrowserDataLoader, width: int, archived: bool
) -> None:
    """Archive an actual process, including recovery from network and HTTP failures."""
    page.set_viewport_size({"width": width, "height": 844})
    data = seed_browser_data(page, scenario="overview")
    overview_url = f"{BASE_URL}/private/keuzecanvas" + ("?archived=1" if archived else "")
    page.goto(overview_url)
    page.get_by_role("button", name="Toon oudere processen").click()
    gid = data["process_gids"][6]
    row = page.locator(f'[data-process-id="{gid}"]')
    next_gid = row.evaluate("row => (row.nextElementSibling || row.previousElementSibling).dataset.processId")
    action = row.get_by_role("link", name="Proces verwijderen")
    action.scroll_into_view_if_needed()
    action.focus()
    archive_url = f"{BASE_URL}/private/team/keuzecanvas/{gid}/archive"
    failures = 2

    def respond_archive(route: Route) -> None:
        nonlocal failures
        if failures == 2:
            failures -= 1
            route.abort("failed")
        elif failures == 1:
            failures -= 1
            route.fulfill(status=503, body="Tijdelijk niet beschikbaar")
        else:
            route.continue_()

    page.route(archive_url, respond_archive)
    page.evaluate("window.overviewDocument = true")
    for _ in range(2):
        with page.expect_request(archive_url):
            action.press("Enter")
        expect(page.locator("#process-overview")).not_to_have_attribute("aria-busy", "true")
        expect(page.get_by_role("alert")).to_contain_text("Probeer het opnieuw")
        expect(action).to_be_focused()

    scroll = page.evaluate("scrollY")
    history_length = page.evaluate("history.length")
    action.press("Enter")
    expect(page.locator("#okl-page-status")).to_have_text(f"Keuzeproces van {data['team_name']} verwijderd.")
    if archived:
        expect(row).to_be_visible()
        expect(row.get_by_role("link", name="Proces verwijderen")).to_have_count(0)
    else:
        expect(row).to_have_count(0)
    next_row = page.locator(f'[data-process-id="{next_gid}"]')
    expect(next_row.locator("[data-process-archive], a[aria-label]").first).to_be_focused()
    expect(page.locator("#show-more")).to_have_attribute("aria-expanded", "true")
    expect(page).to_have_url(overview_url)
    max_scroll = page.evaluate("document.documentElement.scrollHeight - innerHeight")
    assert abs(page.evaluate("scrollY") - min(scroll, max_scroll)) <= 2
    assert page.evaluate("window.overviewDocument") is True
    assert page.evaluate("history.length") == history_length

    page.reload()
    if archived:
        page.get_by_role("button", name="Toon oudere processen").click()
        expect(row).to_be_attached()
    else:
        expect(row).to_have_count(0)
