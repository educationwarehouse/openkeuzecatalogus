"""Browser regressions for the generic admin table browser."""

import uuid
from urllib.parse import urlparse

from playwright.sync_api import Page, expect

from .auth_helpers import _login_as_user, _register_and_verify_user
from .settings import BASE_URL


def test_table_browser_deletes_table_without_editable_companion(page: Page) -> None:
    """Deleting Evidence must redirect normally even though it has no `_ed` model."""
    suffix = uuid.uuid4().hex[:10]
    email = f"table-browser-admin-{suffix}@educationwarehouse.nl"
    password = f"AdminPass!{suffix}123"
    sha1_digest = uuid.uuid4().hex
    _register_and_verify_user(page, email=email, password=password, last_name="Admin")
    _login_as_user(page, email=email, password=password)

    page.goto(f"{BASE_URL}/admin/tables/evidence/new")
    page.locator("textarea[name='source'], input[name='source']").fill('{"test": true}')
    page.locator("input[name='sha1_digest']").fill(sha1_digest)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    expect(page.locator(".grid-table")).to_be_visible()

    evidence_row = page.locator(".grid-table tr", has_text=sha1_digest)
    expect(evidence_row).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    evidence_row.locator(".grid-delete-button").click()

    page.wait_for_url("**/admin/tables/evidence/select**")
    assert urlparse(page.url).path == "/admin/tables/evidence/select"
    expect(page.locator(".grid-table tr", has_text=sha1_digest)).to_have_count(0)
