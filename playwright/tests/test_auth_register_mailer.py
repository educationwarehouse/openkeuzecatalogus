"""Browser test for auth/register mail delivery."""

import json
import re
import time
import typing as t
import uuid

from playwright.sync_api import Page

from .conftest import (
    APPLOG_PATH,
    BASE_URL,
    MOCK_EMAIL_DOMAIN,
    MOCK_INBOX_PATH,
    RESET_PASSWORD_LINK_MAX_AGE_HOURS,
)


def _get_new_email_address(prefix: str, suffix: str | None = None) -> str:
    suffix = uuid.uuid4().hex[:10] if suffix is None else suffix
    return f"{prefix}-{suffix}@{MOCK_EMAIL_DOMAIN}"


def _read_messages() -> list[dict]:
    if not MOCK_INBOX_PATH.exists():
        return []
    lines = [line for line in MOCK_INBOX_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _read_applog_events() -> list[dict]:
    if not APPLOG_PATH.exists():
        return []
    lines = [line for line in APPLOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _extract_verify_url(
    message: dict, pattern: re.Pattern[str] = re.compile(r"https?://[^\s\"'<>]+/auth/verify_email[^\s\"'<>]*")
) -> str | None:
    text = f"{message.get('text_body') or ''}\n{message.get('html_body') or ''}"
    match = pattern.search(text)
    if not match:
        return None
    return match.group(0).replace("&amp;", "&")


def _extract_reset_password_url(
    message: dict, pattern: re.Pattern[str] = re.compile(r"https?://[^\s\"'<>]+/auth/reset_password[^\s\"'<>]*")
) -> str | None:
    text = f"{message.get('text_body') or ''}\n{message.get('html_body') or ''}"
    match = pattern.search(text)
    if not match:
        return None
    return match.group(0).replace("&amp;", "&")


def get_cookies(page: Page, name: str = "shared_session") -> list[dict]:
    """Collect cookies with a specific name from the active Playwright context."""
    return [cookie for cookie in page.context.cookies() if cookie.get("name") == name]


def _wait_for_matching_email(
    email: str,
    matcher: t.Callable[[dict], bool],
    error_message: str,
    max_wait_seconds: int = 10,
    check_interval: float = 0.2,
    start_at: int = 0,
) -> dict | None:
    """Poll inbox until a new message for `email` satisfies `matcher`."""
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        messages = _read_messages()
        for msg in messages[start_at:]:
            if email not in (msg.get("all_recipients") or []):
                continue
            if matcher(msg):
                return msg
        time.sleep(check_interval)
    raise AssertionError(error_message)


def wait_for_email(
    email: str,
    max_wait_seconds: int = 10,
    check_interval: float = 0.2,
    start_at: int = 0,
) -> dict | None:
    """Poll the fake inbox for a recipient and return the first matching message."""
    return _wait_for_matching_email(
        email=email,
        matcher=lambda _msg: True,
        error_message=f"No fake mail found for {email}",
        max_wait_seconds=max_wait_seconds,
        check_interval=check_interval,
        start_at=start_at,
    )


def wait_for_specific_email(
    email: str,
    pattern: re.Pattern[str],
    max_wait_seconds: int = 10,
    check_interval: float = 0.2,
    start_at: int = 0,
) -> dict | None:
    """Poll the fake inbox for a recipient and regex-matched content from new messages."""

    def _pattern_match(msg: dict) -> bool:
        text = f"{msg.get('subject') or ''}\n{msg.get('text_body') or ''}\n{msg.get('html_body') or ''}"
        return pattern.search(text) is not None

    return _wait_for_matching_email(
        email=email,
        matcher=_pattern_match,
        error_message=f"No fake mail found for {email} matching {pattern.pattern}",
        max_wait_seconds=max_wait_seconds,
        check_interval=check_interval,
        start_at=start_at,
    )


def wait_for_auth_markers(
    email: str,
    expected_markers: set[str],
    timeout_seconds: int = 10,
    start_at: int = 0,
) -> set[str]:
    """Wait until applog auth actions for `email` include all expected markers."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        events = _read_applog_events()
        seen = {
            str(event.get("action"))
            for event in events[start_at:]
            if event.get("kind") == "auth_action" and event.get("email") == email
        }
        if expected_markers.issubset(seen):
            return seen
        time.sleep(0.2)

    events = _read_applog_events()
    return {
        str(event.get("action"))
        for event in events[start_at:]
        if event.get("kind") == "auth_action" and event.get("email") == email
    }


def test_entree_mock_login_works_and_logs_success(page: Page) -> None:
    """Use mocked Entree OAuth login and assert first-time registration then later login."""
    applog_start = len(_read_applog_events())

    page.goto(f"{BASE_URL}/auth/login")
    entree_login_button = page.locator("a[href*='oauth2kennisnet']").first
    assert entree_login_button.is_visible(), "Kennisnet Entree Login button is not visible"

    entree_login_button.click()

    page.goto(f"{BASE_URL}/profile")
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

    page.goto(f"{BASE_URL}/profile")
    profile_body = page.text_content("body") or ""
    assert f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}" in profile_body

    markers = wait_for_auth_markers(
        email=f"kennisnet:mock-entree-user@{MOCK_EMAIL_DOMAIN}",
        expected_markers={"login"},
        start_at=applog_after_registration,
    )
    assert "login" in markers
    assert "registration" not in markers


def test_register_sends_verification_mail(page: Page) -> None:
    """Run basic register-login loop test.

    Register, assert unverified access fails, verify via fake mail link,
    then assert login succeeds and session cookie rotates on login/logout.
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
    page.goto(f"{BASE_URL}/profile")
    profile_before_verify = page.text_content("body") or ""
    assert email not in profile_before_verify

    # Login attempt before verification should not grant authenticated access.
    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.goto(f"{BASE_URL}/profile")
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

    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.locator("button[type='submit'], input[type='submit']").first.click()

    page.goto(f"{BASE_URL}/profile")
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

    page.goto(f"{BASE_URL}/profile")
    profile_after_logout = page.text_content("body") or ""
    assert email not in profile_after_logout

    assert APPLOG_PATH.exists(), "applog file does not exist"

    markers = wait_for_auth_markers(
        email=email,
        expected_markers={"login", "logout", "change_password", "invalid_login_attempt"},
    )

    assert "login" in markers  # inloggen
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
    page.goto(f"{BASE_URL}/profile")
    profile_with_old_password = page.text_content("body") or ""
    assert email not in profile_with_old_password

    page.goto(f"{BASE_URL}/auth/login")
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", new_password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.goto(f"{BASE_URL}/profile")
    profile_with_new_password = page.text_content("body") or ""
    assert email in profile_with_new_password
