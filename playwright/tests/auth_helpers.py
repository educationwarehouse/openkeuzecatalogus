"""Shared browser authentication and fake-mail helpers."""

import json
import re
import time
import typing as t
import uuid
from urllib.parse import urlparse

from playwright.sync_api import Page, expect

from .settings import APPLOG_PATH, BASE_URL, MOCK_EMAIL_DOMAIN, MOCK_INBOX_PATH


class BrowserData(t.TypedDict):
    """Records prepared for real-page browser regressions."""

    process_gids: list[str]
    team_name: str
    search_term: str
    material_names: list[str]


type BrowserScenario = t.Literal["process", "overview", "catalog", "material", "package"]


class BrowserDataLoader(t.Protocol):
    """Prepare only the records needed by one browser scenario."""

    def __call__(self, page: Page, scenario: BrowserScenario = "process") -> BrowserData:
        """Authenticate and seed the requested scenario."""
        ...


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


def _extract_magic_login_url(
    message: dict, pattern: re.Pattern[str] = re.compile(r"https?://[^\s\"'<>]+/auth/magic_login[^\s\"'<>]*")
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
    email: str | None,
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
            if event.get("kind") == "auth_action" and (email is None or event.get("email") == email)
        }
        if expected_markers.issubset(seen):
            return seen
        time.sleep(0.2)

    events = _read_applog_events()
    return {
        str(event.get("action"))
        for event in events[start_at:]
        if event.get("kind") == "auth_action" and (email is None or event.get("email") == email)
    }


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


def _create_verified_user(page: Page, *, prefix: str, admin: bool) -> tuple[str, str]:
    """Register a user that is either a regular user or an Education Warehouse admin."""
    suffix = uuid.uuid4().hex[:10]
    domain = "educationwarehouse.nl" if admin else MOCK_EMAIL_DOMAIN
    email = f"{prefix}-{suffix}@{domain}"
    password = f"ContentEdit!{suffix}123"

    _register_and_verify_user(
        page,
        email=email,
        password=password,
        last_name="Admin" if admin else "User",
    )
    return email, password
