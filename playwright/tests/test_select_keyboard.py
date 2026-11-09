"""Keyboard regressions exercise the actual catalogue and process select widgets."""

import re

import pytest
from playwright.sync_api import Page, expect

from .accessibility import AccessibilityReport
from .auth_helpers import BrowserDataLoader
from .settings import BASE_URL


@pytest.fixture(params=[390, 1280])
def select_form(page: Page, request: pytest.FixtureRequest, seed_browser_data: BrowserDataLoader) -> None:
    """Open the process containing real single-select and multiselect widgets."""
    page.set_viewport_size({"width": request.param, "height": 844})
    data = seed_browser_data(page)
    page.goto(f"{BASE_URL}/private/team/keuzecanvas/{data['process_gids'][0]}/fase1")
    widget = page.locator('[data-widget="multi-select"]').first
    expect(widget).to_have_attribute("data-enhanced-capsule-select", "true")
    criteria_form = page.locator('form[hx-post$="/criteria"]')
    expect(criteria_form).not_to_have_class(re.compile(r"\bhtmx-settling\b"))


@pytest.mark.parametrize("width", [390, 1280])
def test_native_select_returns_to_form_tab_order(page: Page, width: int) -> None:
    """Exercise the enhanced native sort control in the real catalogue."""
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(f"{BASE_URL}/producten")
    expect(page.locator("#catalog-filters .okl-skeleton")).to_have_count(0)
    if width < 992:
        page.get_by_role("button", name=re.compile("Filters tonen")).click()
    trigger = page.get_by_role("button", name="Sorteren op: Alfabetisch (A-Z)", exact=True)
    trigger.press("ArrowDown")
    expect(page.get_by_role("option", name="Alfabetisch (A-Z)", exact=True)).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(page.get_by_role("option", name="Alfabetisch (Z-A)", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    trigger.press("ArrowDown")
    page.get_by_role("option", name="Alfabetisch (Z-A)", exact=True).press("Enter")
    expect(page).to_have_url(re.compile("sort=name_desc"))
    expect(page.locator("#catalog-sort")).to_have_value("name_desc")
    trigger = page.get_by_role("button", name="Sorteren op: Alfabetisch (Z-A)", exact=True)
    expect(trigger).to_be_focused()
    page.keyboard.press("Tab")
    expect(trigger).not_to_be_focused()
    expect(trigger).to_have_attribute("aria-expanded", "false")


@pytest.mark.usefixtures("select_form")
def test_single_select_keeps_focus_after_selection_and_dismissal(page: Page) -> None:
    """Select a real team member and preserve the value across reload."""
    trigger = page.get_by_role("button", name="Selecteer een projectleider", exact=True)
    widget = page.locator('[data-widget="single-select"]')
    selection_focus: list[bool] = []

    def record_selection_focus(focused: bool) -> None:
        selection_focus.append(focused)

    page.expose_function("record_selection_focus", record_selection_focus)
    page.evaluate("""() => {
        document.addEventListener("change", event => {
            if (event.target.matches('input[name="project_leader"]')) {
                const $widget = event.target.closest('[data-widget="single-select"]');
                window.record_selection_focus(document.activeElement === $widget.querySelector("button"));
            }
        });
    }""")
    trigger.press("Enter")
    option = widget.get_by_role("option").first
    expect(option).to_be_focused()
    selected_gid = option.get_attribute("data-value")
    with page.expect_navigation():
        option.press("Enter")
    assert selection_focus == [True]
    expect(widget.locator('input[name="project_leader"]')).to_have_value(selected_gid)

    trigger.press("ArrowUp")
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("Tab")
    expect(trigger).not_to_be_focused()
    page.reload()
    expect(widget.locator('input[name="project_leader"]')).to_have_value(selected_gid)


@pytest.mark.usefixtures("select_form")
def test_multiselect_choices_are_reachable_and_close_when_tabbing_out(page: Page) -> None:
    """Use real criterion choices, including search, dismissal and persistence."""
    widget = page.locator('[data-widget="multi-select"]').first
    trigger = widget.get_by_role("button").first
    search = widget.get_by_role("searchbox")
    choices = widget.get_by_role("checkbox")
    trigger.press("Enter")
    expect(search).to_be_focused()
    page.keyboard.press("Tab")
    expect(choices.first).to_be_focused()
    page.keyboard.press("Tab")
    expect(choices.nth(1)).to_be_focused()
    selected_value = choices.nth(1).input_value()
    selected_name = choices.nth(1).get_attribute("name")
    with page.expect_response(
        lambda response: "/criteria" in response.url and response.request.method == "POST"
    ) as saved:
        choices.nth(1).press("Space")
        expect(choices.nth(1)).to_be_checked()
    assert saved.value.ok, saved.value.status
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    expect(trigger).to_have_attribute("aria-expanded", "false")

    trigger.press("Enter")
    search.fill("geen resultaat")
    page.keyboard.press("Enter")
    expect(search).to_be_focused()
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    trigger.press("Enter")
    search.fill("")
    page.keyboard.press("Shift+Tab")
    expect(trigger).to_be_focused()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    page.reload()
    expect(widget.locator(f'input[name="{selected_name}"][value="{selected_value}"]')).to_be_checked()


@pytest.mark.accessibility
@pytest.mark.usefixtures("select_form")
def test_open_selects_accessibility(page: Page, accessibility_report: AccessibilityReport) -> None:
    """Scan the real open process selects and catalogue sort control."""
    page.emulate_media(reduced_motion="reduce")
    for widget in (page.locator('[data-widget="single-select"]'), page.locator('[data-widget="multi-select"]').first):
        trigger = widget.get_by_role("button").first
        trigger.press("Enter")
        accessibility_report.scan(page, f"Geopende proceskeuzelijst bij {page.viewport_size['width']} px")
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()

    page.goto(f"{BASE_URL}/producten")
    expect(page.locator("#catalog-filters .okl-skeleton")).to_have_count(0)
    if page.viewport_size["width"] < 992:
        page.get_by_role("button", name=re.compile("Filters tonen")).click()
    page.get_by_role("button", name="Sorteren op: Alfabetisch (A-Z)", exact=True).press("Enter")
    accessibility_report.scan(page, f"Geopende catalogussortering bij {page.viewport_size['width']} px")
