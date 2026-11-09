"""Advisory WCAG scans for public, interactive, authentication, and admin states."""

import typing as t
import uuid

import pytest
from playwright.sync_api import Page, expect

from .accessibility import AccessibilityReport
from .auth_helpers import _login_as_user, _register_and_verify_user
from .settings import BASE_URL, MOCK_EMAIL_DOMAIN

EMPTY_AUTHENTICATION_FORMS = (
    ("/auth/login", "Inloggen — leeg formulier"),
    ("/auth/register", "Registreren — leeg formulier"),
)


class CatalogScenario(t.TypedDict):
    """Parameters for one public catalogue and its interactive states."""

    path: str
    title: str
    results_id: str
    results_heading: str
    results_endpoint: str


CATALOG_SCENARIOS: tuple[CatalogScenario, ...] = (
    {
        "path": "/producten",
        "title": "Productoverzicht",
        "results_id": "product-results",
        "results_heading": "Producten",
        "results_endpoint": "/htmx/products/results",
    },
    {
        "path": "/methodes",
        "title": "Methodenoverzicht",
        "results_id": "method-results",
        "results_heading": "Methodes",
        "results_endpoint": "/htmx/methods/results",
    },
)


def _wait_for_catalog(page: Page, results_id: str, results_heading: str) -> None:
    """Wait for the catalogue state form and HTMX results to finish rendering."""
    expect(page.locator("#catalog-filters form.edwh-state[data-catalog-filters-enhanced='true']")).to_be_visible()
    expect(page.locator("#catalog-filters .okl-skeleton")).to_have_count(0)
    expect(page.locator(f"#{results_id} h2")).to_contain_text(results_heading)
    expect(page.locator(".htmx-request")).to_have_count(0)


def _scan_catalog_states(
    page: Page,
    report: AccessibilityReport,
    *,
    path: str,
    title: str,
    results_id: str,
    results_heading: str,
    results_endpoint: str,
) -> None:
    """Scan a catalogue in its initial, filtered, and list-view states."""
    page.goto(f"{BASE_URL}{path}")
    expect(page.get_by_role("heading", name="Methodes & Producten", exact=True)).to_be_visible()
    _wait_for_catalog(page, results_id, results_heading)
    report.scan(page, f"{title} — standaardweergave")

    search_input = page.locator("form.edwh-state input[type='search'][name]").first
    if search_input.count():
        with page.expect_response(lambda response: results_endpoint in response.url):
            search_input.fill("toets")
        _wait_for_catalog(page, results_id, results_heading)
        report.scan(page, f"{title} — zoekfilter ingevuld")

    page.get_by_role("button", name="Tegels", exact=True).click()
    with page.expect_response(lambda response: results_endpoint in response.url):
        page.get_by_role("button", name="Lijst", exact=True).click()
    _wait_for_catalog(page, results_id, results_heading)
    expect(page.locator(f"#{results_id} .catalog-results-grid--list")).to_be_attached()
    report.scan(page, f"{title} — lijstweergave")


@pytest.mark.accessibility
def test_public_catalog_accessibility(page: Page, accessibility_report: AccessibilityReport) -> None:
    """Scan both public catalogues after their main interactive state changes."""
    page.emulate_media(reduced_motion="reduce")
    for scenario in CATALOG_SCENARIOS:
        _scan_catalog_states(page, accessibility_report, **scenario)


@pytest.mark.accessibility
def test_authentication_accessibility(page: Page, accessibility_report: AccessibilityReport) -> None:
    """Scan the login, invalid-login, and registration form states."""
    page.emulate_media(reduced_motion="reduce")
    for path, name in EMPTY_AUTHENTICATION_FORMS:
        page.goto(f"{BASE_URL}{path}")
        expect(page.locator("input[name='email']")).to_be_visible()
        accessibility_report.scan(page, name)

    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", f"axe-niet-bestaand@{MOCK_EMAIL_DOMAIN}")
    page.fill("input[name='password']", "NietHetJuisteWachtwoord123!")
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url("**/auth/login")
    expect(page.get_by_text("Ongeldige inloggegevens.")).to_be_visible()
    accessibility_report.scan(page, "Inloggen — ongeldige gegevens zichtbaar")


@pytest.mark.accessibility
def test_admin_accessibility(page: Page, accessibility_report: AccessibilityReport) -> None:
    """Scan representative pages after authenticating as a temporary admin."""
    page.emulate_media(reduced_motion="reduce")
    suffix = uuid.uuid4().hex[:10]
    email = f"axe-admin-{suffix}@educationwarehouse.nl"
    password = f"AxeAdmin!{suffix}123"

    _register_and_verify_user(page, email=email, password=password, last_name="Accessibility")
    _login_as_user(page, email=email, password=password)

    page.goto(f"{BASE_URL}/admin/index")
    expect(page.get_by_role("heading", name="Admin Dashboard", exact=True)).to_be_visible()
    accessibility_report.scan(page, "Admin — dashboard na inloggen")

    page.goto(f"{BASE_URL}/admin/suppliers/select")
    expect(page.locator(".grid-wrapper .grid-table")).to_be_visible()
    accessibility_report.scan(page, "Admin — leveranciersgrid")
