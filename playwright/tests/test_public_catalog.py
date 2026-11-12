"""Browser-level coverage for public catalogue endpoints."""

import pytest
from playwright.sync_api import Browser, Page, expect

from .auth_helpers import BrowserDataLoader, _create_verified_user, _login_as_user
from .settings import BASE_URL


@pytest.mark.parametrize("entity", ["products", "packages"])
def test_product_results_rejects_invalid_budget_filter_with_client_error(page: Page, entity: str) -> None:
    """A manually edited budget filter must not turn the HTMX endpoint into a 500."""
    response = page.request.get(
        f"{BASE_URL}/htmx/{entity}/results",
        params={"bdgt": "abc-def"},
        headers={"HX-Request": "true"},
    )
    assert 400 <= response.status < 500


@pytest.mark.parametrize(("path", "label"), [("producten", "Producten"), ("pakketten", "Pakketten")])
def test_catalog_tabs_link_to_packages_and_products_without_a_type_filter(page: Page, path: str, label: str) -> None:
    """Both public tabs expose their own results while composition stays fixed."""
    page.goto(f"{BASE_URL}/{path}")
    tabs = page.get_by_role("navigation", name="Type leermiddelen")
    expect(tabs.get_by_role("link", name="Pakketten", exact=True)).to_have_attribute("href", "/pakketten")
    expect(tabs.get_by_role("link", name="Producten", exact=True)).to_have_attribute("href", "/producten")
    expect(tabs.get_by_role("link", name="Methodes", exact=True)).to_have_count(0)
    expect(tabs.get_by_role("link", name=label, exact=True)).to_have_attribute("aria-current", "page")
    expect(page.locator(".okl-catalog-results h2")).to_contain_text(label)
    expect(page.locator('#catalog-filter-controls [name="cmp"]')).to_have_count(0)


def test_method_overview_redirects_to_opened_faq_explanation(page: Page) -> None:
    """The former method overview explains its absence and leads visitors to packages."""
    page.goto(f"{BASE_URL}/methodes")

    expect(page).to_have_url(f"{BASE_URL}/faq#waarom-geen-methodes")
    question = page.locator("#waarom-geen-methodes")
    expect(question.get_by_role("button", name="Waarom geen overzicht van methodes?")).to_have_attribute(
        "aria-expanded", "true"
    )
    expect(question.get_by_text("niet eenduidig afgebakend")).to_be_visible()
    expect(question.get_by_role("link", name="→ Naar losse producten")).to_have_attribute("href", "/producten")

    question.get_by_role("link", name="→ Naar pakketten").click()
    expect(page).to_have_url(f"{BASE_URL}/pakketten")
    expect(page.locator(".okl-catalog-results h2")).to_contain_text("Pakketten")


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
        for path in ("pakketten", "producten"):
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


def test_package_detail_lists_its_components_and_components_lead_back(
    page: Page, seed_browser_data: BrowserDataLoader
) -> None:
    """A package page shows its bundled components, and a component page leads back to its package."""
    data = seed_browser_data(page, scenario="package")
    package_name, *component_names = data["material_names"]
    page.goto(f"{BASE_URL}/auth/logout")
    page.goto(f"{BASE_URL}/pakketten")
    expect(page.locator("#catalog-filters .okl-skeleton")).to_have_count(0)
    with page.expect_response(lambda response: "/results" in response.url):
        page.get_by_role("searchbox", name="Zoekterm", exact=True).fill(data["search_term"])
    card = page.locator(".catalog-result-item").filter(has_text=package_name)
    card.get_by_role("link", name="Bekijk pakket", exact=True).click()

    expect(page.locator("main h1")).to_have_text(package_name)
    expect(page.locator(".okl-detail-type")).to_have_text("Pakket")
    expect(page.locator(".okl-detail-meta")).to_contain_text("Pakketvorm")
    expect(page.get_by_text("Gegevens van de methode")).to_have_count(0)
    expect(page.get_by_role("heading", name="Producten behorende bij de methode")).to_have_count(0)
    contents = page.locator("section").filter(has=page.get_by_role("heading", name="Inhoud van dit pakket"))
    expect(contents.locator(".okl-related-product h3")).to_have_text(component_names)
    expect(contents.locator(".comparison-selection")).to_have_count(0)

    contents.get_by_role("link", name=component_names[0], exact=True).click()
    expect(page.locator("main h1")).to_have_text(component_names[0])
    expect(page.locator(".okl-detail-type")).to_have_text("Product")
    expect(page.locator(".okl-detail-meta")).to_contain_text("Onderdeel (niet los verkrijgbaar)")
    expect(page.locator(".okl-detail-compare")).to_have_count(0)
    parents = page.locator("section").filter(has=page.get_by_role("heading", name="Onderdeel van pakket", exact=True))
    expect(parents.locator(".okl-related-product h3")).to_have_text([package_name])

    page.get_by_role("link", name=f"Terug naar pakket {package_name}").click()
    expect(page.locator("main h1")).to_have_text(package_name)
