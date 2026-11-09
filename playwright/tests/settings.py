"""Shared configuration for browser fixtures and test helpers."""

import os
from pathlib import Path

BASE_URL = os.environ.get("WEB_BASE_URL", "http://py4web:8000")
MOCK_INBOX_PATH = Path("/shared_cache/mail/mock_inbox.jsonl")
APPLOG_PATH = Path(os.environ.get("APPLOG_PATH", "/shared_applog/events.jsonl"))
MOCK_EMAIL_DOMAIN = os.environ["PYTEST_MOCK_EMAIL_DOMAIN"]
RESET_PASSWORD_LINK_MAX_AGE_HOURS = 72
