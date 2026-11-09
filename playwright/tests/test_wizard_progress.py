"""Visited wizard steps remain reachable without bypassing the shared save guard."""

import re

import pytest
from playwright.sync_api import Page, Route, expect

from .auth_helpers import BrowserDataLoader
from .settings import BASE_URL


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("storage", [True, False])
def test_visited_wizard_steps(page: Page, seed_browser_data: BrowserDataLoader, width: int, storage: bool) -> None:
    """Restore real visited steps, isolate processes and wait for pending saves."""
    page.set_viewport_size({"width": width, "height": 844})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if not storage:
        page.add_init_script("""Object.defineProperty(window, 'localStorage', {
            get() { throw new DOMException('Storage disabled', 'SecurityError'); }
        });""")
    data = seed_browser_data(page)
    base = f"{BASE_URL}/private/team/keuzecanvas/{data['process_gids'][0]}"
    page.goto(f"{base}/fase1")
    steps = page.locator(".steps")
    expect(steps.locator("a")).to_have_count(0)
    page.get_by_role("link", name="Volgende", exact=True).click()
    expect(page).to_have_url(f"{base}/fase3")
    expect(steps.locator('a[data-step-url$="/fase1"]')).to_have_class(re.compile("completed"))
    expect(steps.locator("a.visited")).to_have_count(0)

    page.go_back()
    expect(page).to_have_url(f"{base}/fase1")
    visited = steps.locator('a[data-step-url$="/fase3"]')
    expect(visited).to_have_class(re.compile("visited"))
    expect(steps.locator('a[data-step-url$="/fase4"]')).to_have_count(0)

    pending: list[Route] = []
    criteria_url = f"{base}/criteria"
    page.route(criteria_url, lambda route: pending.append(route))
    widget = page.locator('[data-widget="multi-select"]').first
    widget.get_by_role("button").first.click()
    widget.get_by_role("checkbox").first.check()
    expect(widget.locator("xpath=ancestor::form")).to_have_class(re.compile("htmx-request"))
    page.keyboard.press("Escape")
    visited.press("Enter", no_wait_after=True)
    expect(page).to_have_url(f"{base}/fase1")
    assert len(pending) == 1
    pending[0].continue_()
    page.unroute(criteria_url)
    expect(page).to_have_url(f"{base}/fase3")
    page.get_by_role("link", name="Volgende", exact=True).click()
    expect(page).to_have_url(f"{base}/fase4")
    steps.locator('a[data-step-url$="/fase1"]').click()
    expect(page).to_have_url(f"{base}/fase1")
    expect(steps.locator("a.visited")).to_have_count(2)
    expect(steps.locator('[aria-current="step"]')).to_have_count(1)
    if storage:
        page.reload()
        expect(steps.locator("a.visited")).to_have_count(2)

    page.goto(f"{BASE_URL}/private/team/keuzecanvas/{data['process_gids'][1]}/fase1")
    expect(steps.locator("a")).to_have_count(0)
    assert not errors, errors
