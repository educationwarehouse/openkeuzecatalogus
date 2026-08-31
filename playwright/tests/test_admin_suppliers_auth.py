"""Browser coverage for `/admin/suppliers` auth and role gating."""

import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from .conftest import BASE_URL, MOCK_EMAIL_DOMAIN
from .test_auth_register_mailer import _extract_verify_url, _read_messages, wait_for_specific_email


def _register_and_verify_user(
    page: Page,
    *,
    email: str,
    password: str,
    last_name: str,
    expected_redirect_path: str | None = None,
) -> None:
    inbox_start = len(_read_messages())

    page.goto(f"{BASE_URL}/auth/register")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.fill("input[name='password_again']", password)
    page.fill("input[name='first_name']", "Playwright")
    page.fill("input[name='last_name']", last_name)
    page.locator("button[type='submit'], input[type='submit']").first.click()

    sent = wait_for_specific_email(
        email=email,
        pattern=re.compile(r"/auth/verify_email"),
        start_at=inbox_start,
    )
    assert sent is not None
    verify_url = _extract_verify_url(sent)
    assert verify_url, "No verify_email URL found in fake mail payload"
    page.goto(verify_url, wait_until="commit")

    if expected_redirect_path:
        assert urlparse(page.url).path == expected_redirect_path

    page.goto(f"{BASE_URL}/auth/logout")


def _login_from_current_page(page: Page, *, email: str, password: str) -> None:
    expect(page.locator("input[name='email']")).to_be_visible()
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.locator("button[type='submit'], input[type='submit']").first.click()


def _login_as_user(page: Page, *, email: str, password: str) -> None:
    page.goto(f"{BASE_URL}/auth/login")
    _login_from_current_page(page, email=email, password=password)


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
