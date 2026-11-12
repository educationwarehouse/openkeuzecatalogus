"""Browser coverage for subject management and reconciliation in the admin."""

import uuid
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, expect

from .auth_helpers import _create_verified_user, _login_as_user
from .settings import BASE_URL


def test_subject_pages_require_the_admin_role(page: Page) -> None:
    """Regular users are sent to the no-roles page instead of seeing subject management."""
    email, password = _create_verified_user(page, prefix="subjects-user", admin=False)
    _login_as_user(page, email=email, password=password)

    page.goto(f"{BASE_URL}/admin/school-subjects/unmatched")

    page.wait_for_url("**/auth/error**")
    assert parse_qs(urlparse(page.url).query).get("type") == ["no-roles"]


def test_unmatched_subject_becomes_a_supported_subject_and_filters_admin_products(page: Page) -> None:
    """Creating a subject from an unknown source name links it and makes it a product grid filter."""
    email, password = _create_verified_user(page, prefix="subjects-admin", admin=True)
    _login_as_user(page, email=email, password=password)
    seeded = page.request.post(f"{BASE_URL}/test_seed_unmatched_subject")
    assert seeded.ok, seeded.text()
    subject = seeded.json()["subject"]
    product_name = seeded.json()["product_name"]

    page.goto(f"{BASE_URL}/admin/school-subjects/unmatched?q={subject}")
    expect(page.locator("#subject-results-status")).to_have_text("1 resultaat")
    page.get_by_role("link", name=f"Vak koppelen: {subject}").click()

    expect(page.locator("input[name='new_name']")).to_have_value(subject)
    page.get_by_role("button", name="Nieuw vak aanmaken").click()

    page.wait_for_url("**/admin/school-subjects/unmatched")
    expect(page.get_by_text("Het nieuwe vak is aangemaakt")).to_be_visible()
    page.goto(f"{BASE_URL}/admin/school-subjects/unmatched?q={subject}")
    expect(page.get_by_text("Geen bronnamen gevonden")).to_be_visible()

    page.goto(f"{BASE_URL}/admin/products/select")
    subject_gid = page.locator("select[name='school_subject'] option", has_text=subject).get_attribute("value")
    assert subject_gid, f"Expected {subject} as a product grid subject option"

    page.goto(f"{BASE_URL}/admin/products/select?school_subject={subject_gid}")
    expect(page.locator(".grid-table tr", has_text=product_name)).to_have_count(1)
    expect(page.get_by_role("navigation", name="breadcrumb").get_by_text(subject)).to_be_visible()


def test_stale_subject_drilldown_returns_not_found(page: Page) -> None:
    """A link to a subject that no longer exists fails clearly instead of listing every product."""
    email, password = _create_verified_user(page, prefix="subjects-stale", admin=True)
    _login_as_user(page, email=email, password=password)

    response = page.goto(f"{BASE_URL}/admin/products/select?school_subject={uuid.uuid4()}")

    assert response is not None
    assert response.status == 404, f"Expected HTTP 404 for a stale subject, got {response.status}"


def test_subjects_cannot_be_deleted_from_the_grid(page: Page) -> None:
    """Deleting would silently drop a catalogue filter option, so the grid offers no delete action."""
    email, password = _create_verified_user(page, prefix="subjects-delete", admin=True)
    _login_as_user(page, email=email, password=password)

    page.goto(f"{BASE_URL}/admin/school-subjects")

    expect(page.locator(".grid-table tbody tr").first).to_be_visible()
    expect(page.locator(".grid-table .grid-delete-button")).to_have_count(0)
