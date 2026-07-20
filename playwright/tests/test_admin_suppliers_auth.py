"""Browser coverage for `/admin/suppliers` auth and role gating."""

import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from .conftest import BASE_URL, MOCK_EMAIL_DOMAIN
from .test_auth_register_mailer import _extract_verify_url, _read_messages, wait_for_specific_email


def _register_and_verify_user(page: Page, *, email: str, password: str, last_name: str) -> None:
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
    page.goto(verify_url)
    page.goto(f"{BASE_URL}/auth/logout")


def _login_from_current_page(page: Page, *, email: str, password: str) -> None:
    expect(page.locator("input[name='email']")).to_be_visible()
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.locator("button[type='submit'], input[type='submit']").first.click()


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
