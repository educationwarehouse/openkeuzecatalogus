"""Browser coverage for `/admin/suppliers` auth and role gating."""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from .auth_helpers import (
    _create_verified_user,
    _login_as_user,
    _login_from_current_page,
    _register_and_verify_user,
)
from .settings import BASE_URL, MOCK_EMAIL_DOMAIN


@pytest.mark.parametrize(
    "protected_path",
    [
        # all these should force a login, then show a grid:
        "/admin/suppliers",
        "/admin/suppliers/select",
        "/admin/suppliers/archive",
    ],
)
def test_admin_suppliers_access_requires_login_and_admin_role(page: Page, protected_path: str) -> None:
    """Ensure login + admin role gate is enforced on the supplier admin grid and archive."""
    regular_suffix = uuid.uuid4().hex[:10]
    admin_suffix = uuid.uuid4().hex[:10]

    regular_email = f"suppliers-user-{regular_suffix}@{MOCK_EMAIL_DOMAIN}"
    regular_password = f"UserPass!{regular_suffix}123"
    admin_email = f"playwright-admin-{admin_suffix}@educationwarehouse.nl"
    admin_password = f"AdminPass!{admin_suffix}123"

    _register_and_verify_user(
        page,
        email=regular_email,
        password=regular_password,
        last_name="User",
    )
    _register_and_verify_user(
        page,
        email=admin_email,
        password=admin_password,
        last_name="Admin",
        expected_redirect_path="/admin/index",
    )

    page.goto(f"{BASE_URL}{protected_path}")
    page.wait_for_url("**/auth/login**")
    login_url = urlparse(page.url)
    assert login_url.path.endswith("/auth/login")
    assert parse_qs(login_url.query).get("next") == [protected_path]

    _login_from_current_page(page, email=regular_email, password=regular_password)
    page.wait_for_url("**/auth/error**")
    error_url = urlparse(page.url)
    assert error_url.path.endswith("/auth/error")
    assert parse_qs(error_url.query).get("type") == ["no-roles"]

    page.goto(f"{BASE_URL}/auth/logout")
    page.goto(f"{BASE_URL}{protected_path}")
    page.wait_for_url("**/auth/login**")

    _login_from_current_page(page, email=admin_email, password=admin_password)
    expect(page.locator(".grid-wrapper .grid-table")).to_be_visible()


def test_build_archive_table_marks_current_and_highlights_changed_fields(page: Page) -> None:
    """Edit a supplier, then assert archive rendering marks/highlights correctly."""
    admin_suffix = uuid.uuid4().hex[:10]
    admin_email = f"playwright-admin-{admin_suffix}@educationwarehouse.nl"
    admin_password = f"AdminPass!{admin_suffix}123"

    _register_and_verify_user(
        page,
        email=admin_email,
        password=admin_password,
        last_name="Admin",
    )
    _login_as_user(page, email=admin_email, password=admin_password)

    supplier_suffix = uuid.uuid4().hex[:8]

    page.goto(f"{BASE_URL}/admin/suppliers/select")
    editable_row = page.locator(".grid-table tr", has=page.get_by_role("button", name="Bewerken")).first
    expect(editable_row).to_be_visible()
    editable_row.get_by_role("button", name="Bewerken").first.click()

    page.wait_for_url("**/admin/suppliers/edit/**")
    edit_url = page.url
    assert "/admin/suppliers/edit/" in edit_url

    expect(page.locator("input[name='name']")).to_be_visible()
    original_name = page.input_value("input[name='name']")
    updated_name = f"{original_name} {supplier_suffix}"

    page.fill("input[name='name']", updated_name)
    page.locator("button[type='submit'], input[type='submit']").first.click()

    archive_url = edit_url.replace("/edit/", "/archive/")

    archive_response = page.request.get(archive_url)
    assert archive_response.ok
    archive_html = archive_response.text()
    assert "archive-container" in archive_html
    assert "current-row" in archive_html
    assert "highlight" in archive_html

    page.goto(archive_url)
    expect(page.locator(".archive-container .grid-table")).to_be_visible()

    table_rows = page.locator(".archive-container .grid-table tr")
    assert table_rows.count() == 3

    current_rows = page.locator(".archive-container .grid-table tr.current-row")
    expect(current_rows).to_have_count(1)
    current_row = current_rows.first

    first_cell = current_row.locator("td").first
    assert first_cell.locator("a", has_text="Versie Terugzetten").count() == 1
    assert "highlight" not in ((first_cell.get_attribute("class") or "").split())
    assert current_row.locator("td.highlight").count() >= 1

    previous_row = table_rows.nth(2)
    assert previous_row.locator("td.highlight").count() == 0
    assert original_name in (previous_row.inner_text() or "")
    assert updated_name in (current_row.inner_text() or "")

    assert page.locator(".archive-container .grid-table th", has_text="Type API endpoint").count() == 0


def test_supplier_cannot_change_own_catalogue_participation_status(page: Page) -> None:
    """The public participation widget reads this status, so only admins may edit it."""
    admin_email, admin_password = _create_verified_user(page, prefix="participation-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    seeded = page.request.post(f"{BASE_URL}/test_seed_supplier")
    assert seeded.ok, seeded.text()
    supplier = seeded.json()
    status_field = page.locator("select[name='catalogue_participation_status']")

    page.goto(f"{BASE_URL}/admin/suppliers/select")
    supplier_row = page.locator(".grid-table tr", has_text=supplier["supplier_name"])
    supplier_row.get_by_role("button", name="Bewerken").first.click()
    page.wait_for_url("**/admin/suppliers/edit/**")
    expect(status_field).to_be_visible()

    page.goto(f"{BASE_URL}/auth/logout")
    supplier_suffix = uuid.uuid4().hex[:10]
    supplier_email = f"supplier-user-{supplier_suffix}@{supplier['email_domain']}"
    supplier_password = f"SupplierPass!{supplier_suffix}123"
    try:
        _register_and_verify_user(page, email=supplier_email, password=supplier_password, last_name="Supplier")
        _login_as_user(page, email=supplier_email, password=supplier_password)

        # Grid action links are signed per session, so the supplier opens the form from their own grid.
        page.goto(f"{BASE_URL}/admin/suppliers/select")
        supplier_row = page.locator(".grid-table tr", has_text=supplier["supplier_name"])
        supplier_row.get_by_role("button", name="Bewerken").first.click()
        page.wait_for_url("**/admin/suppliers/edit/**")
        expect(page.locator("input[name='name']")).to_be_visible()
        expect(status_field).to_have_count(0)
    finally:
        cleanup = page.request.post(f"{BASE_URL}/auth/cleanup_mock_users", params={"domain": supplier["email_domain"]})
        assert cleanup.ok, cleanup.text()
