"""Browser test for auth/register mail delivery."""

import re
import uuid

from playwright.sync_api import Page

from .auth_helpers import (
    _extract_magic_login_url,
    _extract_reset_password_url,
    _extract_verify_url,
    _get_new_email_address,
    _read_applog_events,
    _read_messages,
    get_cookies,
    wait_for_auth_markers,
    wait_for_email,
    wait_for_specific_email,
)
from .settings import APPLOG_PATH, BASE_URL, MOCK_EMAIL_DOMAIN, RESET_PASSWORD_LINK_MAX_AGE_HOURS


def test_entree_mock_login_works_and_logs_success(page: Page) -> None:
    """Use mocked Entree OAuth login and assert first-time registration then later login."""
    applog_start = len(_read_applog_events())

    page.goto(f"{BASE_URL}/auth/login")
    entree_login_button = page.locator("a[href*='oauth2kennisnet']").first
    assert entree_login_button.is_visible(), "Kennisnet Entree Login button is not visible"

    entree_login_button.click()

    page.goto(f"{BASE_URL}/auth/profile")
    profile_body = page.text_content("body") or ""
    assert f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}" in profile_body

    markers = wait_for_auth_markers(
        email=f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}",
        expected_markers={"registration"},
        start_at=applog_start,
    )
    assert "registration" in markers

    applog_after_registration = len(_read_applog_events())

    page.goto(f"{BASE_URL}/auth/logout")
    page.goto(f"{BASE_URL}/auth/login")
    entree_login_button = page.locator("a[href*='oauth2kennisnet']").first
    assert entree_login_button.is_visible(), "Kennisnet Entree Login button is not visible"

    entree_login_button.click()

    page.goto(f"{BASE_URL}/auth/profile")
    profile_body = page.text_content("body") or ""
    assert f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}" in profile_body

    markers = wait_for_auth_markers(
        email=f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}",
        expected_markers={"login"},
        start_at=applog_after_registration,
    )
    assert "login" in markers
    assert "registration" not in markers


def test_sso_user_can_request_and_use_magic_login_link(page: Page) -> None:
    """Use mocked Entree login, then authenticate through the SSO magic-link fallback."""
    sso_email = f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}"
    request_email = f"mock-entree-user@{MOCK_EMAIL_DOMAIN}"
    inbox_start = len(_read_messages())
    applog_start = len(_read_applog_events())

    page.goto(f"{BASE_URL}/auth/login")
    entree_login_button = page.locator("a[href*='oauth2kennisnet']").first
    assert entree_login_button.is_visible(), "Kennisnet Entree Login button is not visible"
    entree_login_button.click()

    page.goto(f"{BASE_URL}/auth/logout")
    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", request_email)
    page.fill("input[name='password']", "NotTheSSOPassword123!")
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url("**/auth/login**")

    magic_request_link = page.locator("a[href*='/auth/request_magic_login']").first
    magic_request_link.wait_for(state="visible", timeout=5000)
    magic_request_link.click()
    page.wait_for_url("**/auth/login")

    magic_mail = wait_for_specific_email(
        email=request_email,
        pattern=re.compile(r"/auth/magic_login"),
        start_at=inbox_start,
    )
    assert magic_mail is not None
    assert magic_mail.get("subject") == "Magic login-link"

    magic_url = _extract_magic_login_url(magic_mail)
    assert magic_url, "No magic_login URL found in fake mail payload"

    page.goto(magic_url)
    page.goto(f"{BASE_URL}/auth/profile")
    profile_body = page.text_content("body") or ""
    assert sso_email in profile_body

    markers = wait_for_auth_markers(
        email=sso_email,
        expected_markers={"magic_login"},
        start_at=applog_start,
    )
    assert "magic_login" in markers


def test_sso_user_can_reset_password_via_plain_email(page: Page) -> None:
    """Allow an Entree user to set a local password through the email fallback."""
    sso_email = f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}"
    email = f"mock-entree-user@{MOCK_EMAIL_DOMAIN}"
    new_password = f"SSOFallback!{uuid.uuid4().hex}"
    inbox_start = len(_read_messages())
    applog_start = len(_read_applog_events())

    page.goto(f"{BASE_URL}/auth/login")
    page.locator("a[href*='oauth2kennisnet']").first.click()
    page.goto(f"{BASE_URL}/auth/logout")

    page.goto(f"{BASE_URL}/auth/request_reset_password")
    entree_login_link = page.locator("a[href='/auth/plugin/oauth2kennisnet/login']")
    assert entree_login_link.is_visible()
    page.fill("input[name='email']", email)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url("**/auth/login")

    reset_mail = wait_for_specific_email(
        email=email,
        pattern=re.compile(r"/auth/reset_password"),
        start_at=inbox_start,
    )
    assert reset_mail is not None
    reset_url = _extract_reset_password_url(reset_mail)
    assert reset_url, "No reset_password URL found in fake mail payload"
    page.goto(reset_url)

    page.fill("input[name='new_password']", new_password)
    page.fill("input[name='new_password_again']", new_password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url("**/auth/login")

    page.fill("input[name='email']", email)
    page.fill("input[name='password']", new_password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.goto(f"{BASE_URL}/auth/profile")
    assert sso_email in (page.text_content("body") or "")

    markers = wait_for_auth_markers(
        email=None,
        expected_markers={"sso-reset-option-opened", "sso-reset-requested", "sso-password-reset"},
        start_at=applog_start,
    )
    assert {"sso-reset-option-opened", "sso-reset-requested", "sso-password-reset"}.issubset(markers)


def test_register_sends_verification_mail(page: Page) -> None:
    """Run basic register-login loop test.

    Register, assert unverified access fails, verify via fake mail link,
    then assert verification auto-logs the user in and session cookie rotates on login/logout.
    """
    suffix = uuid.uuid4().hex[:10]
    email = _get_new_email_address("register-mailer", suffix=suffix)
    password = f"Pass!{suffix}123"
    changed_password = f"Changed!{suffix}789"
    initial_cookies = get_cookies(page)
    initial_session_value = initial_cookies[0]["value"] if initial_cookies else None

    page.goto(f"{BASE_URL}/auth/register")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.fill("input[name='password_again']", password)

    first_name = page.locator("input[name='first_name']")
    first_name.fill("Playwright")

    last_name = page.locator("input[name='last_name']")
    last_name.fill("Mailer")

    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url("**/auth/login")

    # Account should not be able to access protected page before email verification.
    page.goto(f"{BASE_URL}/auth/profile")
    profile_before_verify = page.text_content("body") or ""
    assert email not in profile_before_verify

    # Login attempt before verification should not grant authenticated access.
    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.goto(f"{BASE_URL}/auth/profile")
    profile_after_unverified_login = page.text_content("body") or ""
    assert email not in profile_after_unverified_login

    sent = wait_for_email(email)

    assert sent is not None
    assert sent.get("subject")
    assert sent.get("subject") == "Bevestig je e-mailadres"
    assert "Hallo Playwright" in (sent.get("text_body") or "")
    assert "om je e-mailadres te bevestigen" in (sent.get("text_body") or "")

    verify_url = _extract_verify_url(sent)
    assert verify_url, "No verify_email URL found in fake mail payload"

    page.goto(verify_url)
    # Verification now establishes the session, so protected access should succeed immediately.
    page.goto(f"{BASE_URL}/auth/profile")
    profile_body = page.text_content("body") or ""
    assert email in profile_body

    auth_cookies = get_cookies(page)
    assert auth_cookies
    logged_in_session_value = auth_cookies[0]["value"]
    assert logged_in_session_value != initial_session_value

    page.goto(f"{BASE_URL}/auth/change_password")
    page.fill("input[name='old_password']", password)
    page.fill("input[name='new_password']", changed_password)
    page.fill("input[name='new_password_again']", changed_password)
    page.locator("button[type='submit'], input[type='submit']").first.click()

    page.goto(f"{BASE_URL}/auth/logout")
    cookies_after_logout = get_cookies(page)
    assert cookies_after_logout
    logged_out_session_value = cookies_after_logout[0]["value"]
    assert logged_out_session_value != logged_in_session_value

    page.goto(f"{BASE_URL}/auth/profile")
    profile_after_logout = page.text_content("body") or ""
    assert email not in profile_after_logout

    assert APPLOG_PATH.exists(), "applog file does not exist"

    markers = wait_for_auth_markers(
        email=email,
        expected_markers={"verify_email", "logout", "change_password", "invalid_login_attempt"},
    )

    assert "verify_email" in markers  # e-mail verifiëren en automatisch inloggen
    assert "logout" in markers  # uitloggen
    assert "change_password" in markers  # wachtwoord wijzigen
    assert "invalid_login_attempt" in markers  # verkeerde inlogpoging


def test_reset_password_with_registered_account(page: Page) -> None:
    """Register and verify user, then reset password for the same account."""
    suffix = uuid.uuid4().hex[:10]
    email = _get_new_email_address("register-mailer-reset", suffix=suffix)
    password = f"Pass!{suffix}123"
    new_password = f"NewPass!{suffix}456"

    inbox_before_register = len(_read_messages())

    page.goto(f"{BASE_URL}/auth/register")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.fill("input[name='password_again']", password)
    page.fill("input[name='first_name']", "Playwright")
    page.fill("input[name='last_name']", "Reset")
    page.locator("button[type='submit'], input[type='submit']").first.click()

    sent = wait_for_specific_email(
        email=email,
        pattern=re.compile(r"/auth/verify_email"),
        start_at=inbox_before_register,
    )
    assert sent is not None
    verify_url = _extract_verify_url(sent)
    assert verify_url, "No verify_email URL found in fake mail payload"
    page.goto(verify_url)

    # logout before reset password:
    page.goto(f"{BASE_URL}/auth/logout")

    inbox_before_reset_request = len(_read_messages())

    page.goto(f"{BASE_URL}/auth/request_reset_password")
    page.fill("input[name='email']", email)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url("**/auth/login")

    reset_mail = wait_for_specific_email(
        email=email,
        pattern=re.compile(r"/auth/reset_password"),
        start_at=inbox_before_reset_request,
    )
    assert reset_mail is not None
    assert reset_mail.get("subject") == "Wachtwoord opnieuw instellen"
    assert "Hallo Playwright" in (reset_mail.get("text_body") or "")
    assert f"Deze link is slechts {RESET_PASSWORD_LINK_MAX_AGE_HOURS} uur geldig." in (
        reset_mail.get("text_body") or ""
    )
    reset_url = _extract_reset_password_url(reset_mail)
    assert reset_url, "No reset_password URL found in fake mail payload"
    page.goto(reset_url)

    page.fill("input[name='new_password']", new_password)
    page.fill("input[name='new_password_again']", new_password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url("**/auth/login")

    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.goto(f"{BASE_URL}/auth/profile")
    profile_with_old_password = page.text_content("body") or ""
    assert email not in profile_with_old_password

    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", new_password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.goto(f"{BASE_URL}/auth/profile")
    profile_with_new_password = page.text_content("body") or ""
    assert email in profile_with_new_password
