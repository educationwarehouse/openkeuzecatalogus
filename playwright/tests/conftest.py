"""Shared Playwright fixtures for side-effect cleanup, auth session isolation, and mock-user cleanup."""

import os
from pathlib import Path
from urllib.parse import urljoin

import pytest
import requests
from playwright.sync_api import Page

BASE_URL = os.environ.get("WEB_BASE_URL", "http://py4web:8000")
MOCK_INBOX_PATH = Path("/shared_cache/mail/mock_inbox.jsonl")
APPLOG_PATH = Path(os.environ.get("APPLOG_PATH", "/shared_applog/events.jsonl"))
MOCK_EMAIL_DOMAIN = os.environ["PYTEST_MOCK_EMAIL_DOMAIN"]
RESET_PASSWORD_LINK_MAX_AGE_HOURS = 72


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
