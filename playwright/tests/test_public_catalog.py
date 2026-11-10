"""Browser-level coverage for public catalogue endpoints."""

from playwright.sync_api import Browser, Page, expect

from .auth_helpers import _create_verified_user, _login_as_user
from .settings import BASE_URL


def test_product_results_rejects_invalid_budget_filter_with_client_error(page: Page) -> None:
    """A manually edited budget filter must not turn the HTMX endpoint into a 500."""
    response = page.request.get(
        f"{BASE_URL}/htmx/products/results",
        params={"bdgt": "abc-def"},
        headers={"HX-Request": "true"},
    )
    assert 400 <= response.status < 500


def test_catalog_theme_visibility_setting_persists_for_methods_and_products(page: Page, browser: Browser) -> None:
    """Save both settings and hide entire insight sections for anonymous visitors."""
    email, password = _create_verified_user(page, prefix="catalog-settings", admin=True)
    _login_as_user(page, email=email, password=password)
    page.goto(f"{BASE_URL}/admin/catalog-settings")
    switch = page.get_by_role("switch", name="Toon de 12 thema's bij methodes en producten")
    # The browser suite starts from a migrated database without a theme setting.
    expect(switch).to_be_checked()
    limit = page.get_by_label("Maximaal aantal soortgelijke leermiddelen")
    original_limit = limit.input_value()
    changed_limit = "3" if original_limit != "3" else "4"

    with browser.new_context() as visitor_context:
        visitor = visitor_context.new_page()
        details: list[dict[str, str]] = []
        for path in ("methodes", "producten"):
            visitor.goto(f"{BASE_URL}/{path}")
            link = visitor.locator(".catalog-result-item h3 a").first
            expect(link).to_be_visible()
            link.click()
            expect(visitor.get_by_role("heading", name="Inzichten", exact=True)).to_be_visible()
            details.append(
                {
                    "url": visitor.url,
                    "heading": visitor.locator("main h1").inner_text(),
                    "insights": visitor.locator(".okl-insights").inner_text(),
                    "specifications": visitor.locator(".okl-detail-specifications").inner_text(),
                }
            )

        try:
            for show_themes in (False, True):
                page.goto(f"{BASE_URL}/admin/catalog-settings")
                switch.set_checked(show_themes)
                limit.fill(changed_limit)
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST" and response.url.endswith("/admin/catalog-settings/save")
                    )
                ) as saved:
                    page.get_by_role("button", name="Opslaan", exact=True).click()
                assert 200 <= saved.value.status < 400
                expect(page.locator(".htmx-request")).to_have_count(0)
                expect(page).to_have_url(f"{BASE_URL}/admin/catalog-settings")
                page.reload()
                expect(switch).to_be_checked(checked=show_themes)
                expect(limit).to_have_value(changed_limit)

                for detail in details:
                    visitor.goto(detail["url"])
                    expect(visitor.locator("main h1")).to_have_text(detail["heading"])
                    expect(visitor.get_by_role("heading", name="Specificaties", exact=True)).to_be_visible()
                    assert visitor.locator(".okl-detail-specifications").inner_text() == detail["specifications"]
                    if show_themes:
                        expect(visitor.get_by_role("heading", name="Inzichten", exact=True)).to_be_visible()
                        assert visitor.locator(".okl-insights").inner_text() == detail["insights"]
                    else:
                        expect(visitor.locator(".okl-insights")).to_have_count(0)
                        expect(visitor.locator("#insights-title")).to_have_count(0)
        finally:
            response = page.request.post(
                f"{BASE_URL}/admin/catalog-settings/save",
                form={"suggestion_limit": original_limit, "show_themes": "on"},
            )
            assert response.ok
