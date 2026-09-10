"""Browser coverage for Content Editable access control and persistence."""

import uuid

from playwright.sync_api import Page, expect

from .conftest import BASE_URL, MOCK_EMAIL_DOMAIN
from .test_admin_suppliers_auth import _login_as_user, _register_and_verify_user

INTRODUCTION_REGION = "method_overview#method-overview-introduction"


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


def test_content_editor_initializes_only_for_admins(page: Page) -> None:
    """Only admins receive the active ContentTools editor on public overview pages."""
    page.goto(f"{BASE_URL}/methodes")
    expect(page.locator(f"[data-name='{INTRODUCTION_REGION}']")).to_be_visible()
    assert "Only available for authenticated users." in page.evaluate("window.ew_start_editor.toString()")
    expect(page.locator(".ct-ignition")).to_have_count(0)

    regular_email, regular_password = _create_verified_user(page, prefix="content-editor-user", admin=False)
    _login_as_user(page, email=regular_email, password=regular_password)
    page.goto(f"{BASE_URL}/methodes")
    assert "Only available for authenticated users." in page.evaluate("window.ew_start_editor.toString()")
    expect(page.locator(".ct-ignition")).to_have_count(0)

    page.goto(f"{BASE_URL}/auth/logout")
    admin_email, admin_password = _create_verified_user(page, prefix="content-editor-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/methodes")

    assert "ContentTools.EditorApp.get" in page.evaluate("window.ew_start_editor.toString()")
    expect(page.locator(f"[data-name='{INTRODUCTION_REGION}']")).to_be_visible()
    expect(page.locator(".ct-ignition.ct-ignition--ready")).to_be_attached()


def test_content_editor_save_api_rejects_non_admins(page: Page) -> None:
    """The save endpoint rejects anonymous and regular-user requests."""
    payload = {INTRODUCTION_REGION: "<p>Unauthorized change</p>"}

    anonymous_response = page.request.post(
        f"{BASE_URL}/api/content-editable/save",
        form=payload,
        max_redirects=0,
    )
    assert not anonymous_response.ok

    regular_email, regular_password = _create_verified_user(page, prefix="content-api-user", admin=False)
    _login_as_user(page, email=regular_email, password=regular_password)

    regular_response = page.request.post(
        f"{BASE_URL}/api/content-editable/save",
        form=payload,
        max_redirects=0,
    )
    assert not regular_response.ok


def test_content_editor_reports_failed_save_after_logout(page: Page) -> None:
    """A logged-out editor must show a failed-save confirmation."""
    admin_email, admin_password = _create_verified_user(page, prefix="content-expired-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/methodes")
    expect(page.locator(".ct-ignition.ct-ignition--ready")).to_be_attached()

    unsaved_content = f"<p>Unsaved Playwright content {uuid.uuid4().hex}</p>"
    page.request.get(f"{BASE_URL}/auth/logout")

    with page.expect_response(
        lambda response: response.request.method == "POST" and response.url == f"{BASE_URL}/api/content-editable/save",
    ) as response_info:
        page.evaluate(
            """([region, content]) => {
                const editor = ContentTools.EditorApp.get();
                editor.dispatchEvent(editor.createEvent('saved', {regions: {[region]: content}}));
            }""",
            [INTRODUCTION_REGION, unsaved_content],
        )

    assert response_info.value.status != 200
    expect(page.locator(".ct-flash--no")).to_be_attached()
    page.goto(f"{BASE_URL}/methodes")
    assert unsaved_content not in page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html()


def test_content_editor_admin_save_is_rendered_on_public_page(page: Page) -> None:
    """An admin save persists and replaces the matching public-page content region."""
    admin_email, admin_password = _create_verified_user(page, prefix="content-save-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/methodes")

    region = page.locator(f"[data-name='{INTRODUCTION_REGION}']")
    original_content = region.inner_html()
    updated_content = f"<p>Playwright content {uuid.uuid4().hex}</p>"

    try:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: updated_content},
        )
        assert response.ok

        page.goto(f"{BASE_URL}/methodes")
        assert page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html() == updated_content
    finally:
        page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: original_content},
        )


def test_content_editor_preserves_blank_saved_content(page: Page) -> None:
    """A saved empty region must not fall back to its template default after reload."""
    admin_email, admin_password = _create_verified_user(page, prefix="content-blank-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/methodes")

    original_content = page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html()

    try:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: ""},
        )
        assert response.ok

        page.goto(f"{BASE_URL}/methodes")
        assert page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html() == ""
    finally:
        page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: original_content},
        )
