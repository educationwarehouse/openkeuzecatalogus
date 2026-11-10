"""Shared Playwright fixtures for side-effect cleanup, auth session isolation, and mock-user cleanup."""

import typing as t
from urllib.parse import urljoin

import pytest
import requests
from playwright.sync_api import Page

from .accessibility import AXE_REPORT_PATH, AccessibilityReport
from .auth_helpers import BrowserData, BrowserDataLoader, BrowserScenario, _create_verified_user, _login_as_user
from .settings import APPLOG_PATH, BASE_URL, MOCK_EMAIL_DOMAIN, MOCK_INBOX_PATH


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, t.Any]) -> dict[str, t.Any]:
    """Give browser contexts and their API requests the application's origin."""
    headers = browser_context_args.get("extra_http_headers", {}) | {"Origin": BASE_URL}

    return browser_context_args | {"extra_http_headers": headers}


@pytest.fixture
def seed_browser_data(clear_auth_session_state: None) -> BrowserDataLoader:
    """Log in and prepare records for real application pages."""

    def prepare(page: Page, scenario: BrowserScenario = "process") -> BrowserData:
        email, password = _create_verified_user(page, prefix="browser-ui", admin=True)
        _login_as_user(page, email=email, password=password)
        response = page.request.post(f"{BASE_URL}/test_seed_browser_data", form={"scenario": scenario})
        assert response.ok, response.text()

        return response.json()

    return prepare


@pytest.fixture(scope="session")
def accessibility_report() -> t.Iterator[AccessibilityReport]:
    """Collect all axe results and persist them after the browser suite."""
    AXE_REPORT_PATH.unlink(missing_ok=True)
    report = AccessibilityReport()
    yield report
    report.write()
    if report.has_violations:
        pytest.fail("axe-core reported accessibility violations; see axe-report.md for details.")


@pytest.fixture(autouse=True)
def clear_fake_side_effect_files() -> None:
    """Prevent cross-test interference from fake inbox/applog artifacts."""
    MOCK_INBOX_PATH.unlink(missing_ok=True)
    MOCK_INBOX_PATH.touch()
    APPLOG_PATH.unlink(missing_ok=True)
    APPLOG_PATH.touch()


@pytest.fixture(autouse=True)
def clear_mock_users() -> None:
    """Delete mock auth users before and after each test."""

    def _cleanup() -> None:
        response = requests.post(
            urljoin(BASE_URL, "/auth/cleanup_mock_users"),
            params={"domain": MOCK_EMAIL_DOMAIN},
            timeout=10,
        )
        response.raise_for_status()

    _cleanup()
    try:
        yield
    finally:
        _cleanup()


@pytest.fixture(autouse=True)
def clear_auth_session_state(page: Page) -> None:
    """Clear browser cookies before each test to avoid auth state leakage."""
    page.context.clear_cookies()
