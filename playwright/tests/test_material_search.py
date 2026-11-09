"""Material search keeps touch focus within the opening gesture and supports covers."""

import typing as t

import pytest
from playwright.sync_api import BrowserContext, expect

from .auth_helpers import BrowserDataLoader
from .settings import BASE_URL


@pytest.mark.parametrize("touch", [False, True])
def test_material_search_focus_and_covers(
    new_context: t.Callable[..., BrowserContext], seed_browser_data: BrowserDataLoader, touch: bool
) -> None:
    """Keep opening focus, cover layout and keyboard navigation stable across reopenings."""
    context = new_context(has_touch=touch, viewport={"width": 390 if touch else 1280, "height": 844})
    page = context.new_page()
    data = seed_browser_data(page, scenario="material")
    page.goto(f"{BASE_URL}/private/team/keuzecanvas/{data['process_gids'][0]}/fase1")
    page.evaluate("""() => {
        document.addEventListener('click', event => {
            if (event.target.closest('.leermiddelen-search-trigger')) {
                window.focusDuringClick = document.activeElement.matches('.leermiddelen-search-input');
            }
        });
    }""")
    trigger = page.get_by_role("button", name="Open zoekvenster voor leermiddelen", exact=True)
    search = page.get_by_role("searchbox", name="Zoek leermiddelen")
    for _ in range(2):
        if touch:
            trigger.tap()
        else:
            trigger.press("Enter")
        expect(search).to_be_focused()
        if touch:
            assert page.evaluate("window.focusDuringClick") is True
        expect(page.locator(".modal-backdrop")).to_have_count(1)
        search.fill(data["search_term"])
        results = page.locator(".leermiddelen-search-result-action")
        with_cover = results.filter(has_text=data["material_names"][0]).first
        expect(with_cover).to_be_visible()
        expect(results.filter(has_text=data["material_names"][1]).first).to_be_visible()
        image = with_cover.locator(".leermiddelen-search-result-image")
        expect(image).to_be_visible()
        assert image.evaluate("image => image.naturalWidth > 0")
        assert image.evaluate(
            "image => { const row = image.closest('li'); return row.scrollHeight <= row.clientHeight; }"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        search.press("ArrowDown")
        expect(results.first).to_be_focused()
        results.first.press("ArrowUp")
        expect(search).to_be_focused()
        search.press("Escape")
        expect(trigger).to_be_focused()
        expect(page.locator(".modal-backdrop")).to_have_count(0)
    context.close()
