"""Browser coverage for Content Editable access control and persistence."""

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from .auth_helpers import _create_verified_user, _login_as_user
from .settings import BASE_URL

INTRODUCTION_REGION = "package_overview#package-overview-introduction"
PARTICIPATION_TITLE_REGION = "components/catalogue_participation#catalogue-participation-title"


@pytest.mark.parametrize(
    ("status", "color_class"),
    [
        ("Done", "bg-emerald-tint"),
        ("In progress", "bg-sky-tint"),
        ("To-do", "bg-amber-tint"),
        ("Later", "bg-body-secondary"),
    ],
)
def test_milestone_badge_color_follows_edited_status(page: Page, status: str, color_class: str) -> None:
    """The server renders the correct badge color after saving and reloading its status."""
    email, password = _create_verified_user(page, prefix="status-badge", admin=True)
    _login_as_user(page, email=email, password=password)
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{BASE_URL}/")
    identifier = "index#planning-span-3"
    badge = page.locator(f"[data-name='{identifier}']")
    original_content = badge.inner_html()

    try:
        page.locator(".ct-ignition__button--edit").click()
        text = badge.locator("p")
        text.click()
        text.press("ControlOrMeta+A")
        text.press_sequentially(status)
        with page.expect_response(
            lambda response: (
                response.request.method == "POST" and response.url == f"{BASE_URL}/api/content-editable/save"
            ),
        ) as saved:
            page.locator(".ct-ignition__button--confirm").click()
        assert saved.value.ok, f"Expected status save to succeed, got HTTP {saved.value.status}"

        page.reload()
        expect(badge).to_have_text(status)
        expect(badge).to_have_class(re.compile(rf"\b{color_class}\b"))
    finally:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={identifier: original_content},
        )
        assert response.ok, f"Expected original badge content to be restored, got HTTP {response.status}"


@pytest.mark.parametrize(
    ("identifier", "child_selector"),
    [
        ("index#hero-btn-label", "p"),
        ("index#hoe-werkt-het-button-2", "p"),
        ("index#deelnemen-div", "a"),
    ],
)
def test_editable_click_does_not_follow_links_or_toggle_buttons(
    page: Page, identifier: str, child_selector: str
) -> None:
    """A normal click focuses real editable content without activating surrounding controls."""
    email, password = _create_verified_user(page, prefix="content-click", admin=True)
    _login_as_user(page, email=email, password=password)
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{BASE_URL}/")
    page.locator(".ct-ignition__button--edit").click()
    expect(page.locator("body")).to_have_class(re.compile(r"\bcontent-edit-activated\b"))

    target = page.locator(f"[data-name='{identifier}'] {child_selector}")
    target.scroll_into_view_if_needed()
    original_url = page.url
    button = page.locator("button[aria-controls='accHoe-1']")
    original_expanded = button.get_attribute("aria-expanded")
    assert original_expanded is not None, "Expected the accordion button to expose aria-expanded"

    target.click()

    assert page.url == original_url, "Expected an editable click to keep the current page URL"
    expect(button).to_have_attribute("aria-expanded", original_expanded)
    expect(target.locator("xpath=ancestor-or-self::*[@contenteditable][1]")).to_be_focused()

    target.click()
    expect(page).to_have_url(original_url)
    expect(button).to_have_attribute("aria-expanded", original_expanded)

    page.locator(".ct-ignition__button--confirm").click()
    target.click()
    if identifier == "index#hoe-werkt-het-button-2":
        expect(button).to_have_attribute("aria-expanded", "true")
    else:
        expect(page).not_to_have_url(original_url)


@pytest.mark.parametrize(
    ("route", "identifier", "expected_status"),
    [
        ("/", "index#hero-title", 200),
        ("/privacyverklaring", "privacyverklaring#introduction-h1", 200),
        ("/auth/error", "account_access#catalog-page-h1", 200),
        ("/asdfg", "error_404#title", 404),
    ],
)
def test_static_page_content_can_be_saved(page: Page, route: str, identifier: str, expected_status: int) -> None:
    """Static pages use the existing admin editor and retain saved content on reload."""
    response = page.goto(f"{BASE_URL}{route}")
    assert response is not None, f"Expected a response for {route}"
    assert response.status == expected_status, f"Expected HTTP {expected_status} for {route}, got {response.status}"
    expect(page.locator(f"[data-name='{identifier}']")).to_be_visible()
    expect(page.locator(".ct-ignition")).to_have_count(0)

    email, password = _create_verified_user(page, prefix="static-content", admin=True)
    _login_as_user(page, email=email, password=password)
    page.goto(f"{BASE_URL}{route}")
    expect(page.locator(".ct-ignition.ct-ignition--ready")).to_be_attached()
    original_content = page.locator(f"[data-name='{identifier}']").inner_html()
    updated_content = f"<h1>Static content {uuid.uuid4().hex}</h1>"

    try:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={identifier: updated_content},
        )
        assert response.ok, f"Expected content save to succeed, got HTTP {response.status}"
        response = page.reload()
        assert response is not None, f"Expected a response for {route}"
        assert response.status == expected_status, f"Expected HTTP {expected_status} for {route}, got {response.status}"
        assert page.locator(f"[data-name='{identifier}']").inner_html() == updated_content, (
            "Expected saved page content after reload"
        )
        if expected_status == 404:
            expect(page.locator(".error-code")).to_have_text("404")
    finally:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={identifier: original_content},
        )
        assert response.ok, f"Expected content save to succeed, got HTTP {response.status}"


@pytest.mark.parametrize("route", ["/static/missing-asset.css", "/wp-login.php", "/.env"])
def test_missing_assets_render_the_standard_not_found_page(page: Page, route: str) -> None:
    """Missing files and bot probes skip the editable 404 content lookup."""
    response = page.request.get(f"{BASE_URL}{route}")

    assert response.status == 404, f"Expected HTTP 404 for {route}, got {response.status}"
    assert "data-editable" not in response.text(), f"Expected the standard 404 page for {route}"


def test_content_editor_initializes_only_for_admins(page: Page) -> None:
    """Only admins receive the active ContentTools editor on public overview pages."""
    page.goto(f"{BASE_URL}/pakketten")
    expect(page.locator(f"[data-name='{INTRODUCTION_REGION}']")).to_be_visible()
    assert "Only available for authenticated users." in page.evaluate("window.ew_start_editor.toString()"), (
        "Expected the editor to be unavailable to non-admins"
    )
    expect(page.locator(".ct-ignition")).to_have_count(0)

    regular_email, regular_password = _create_verified_user(page, prefix="content-editor-user", admin=False)
    _login_as_user(page, email=regular_email, password=regular_password)
    page.goto(f"{BASE_URL}/pakketten")
    assert "Only available for authenticated users." in page.evaluate("window.ew_start_editor.toString()"), (
        "Expected the editor to be unavailable to non-admins"
    )
    expect(page.locator(".ct-ignition")).to_have_count(0)

    page.goto(f"{BASE_URL}/auth/logout")
    admin_email, admin_password = _create_verified_user(page, prefix="content-editor-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/pakketten")

    assert "ContentTools.EditorApp.get" in page.evaluate("window.ew_start_editor.toString()"), (
        "Expected the admin editor initialization"
    )
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
    assert not anonymous_response.ok, f"Expected anonymous save to be rejected, got HTTP {anonymous_response.status}"

    regular_email, regular_password = _create_verified_user(page, prefix="content-api-user", admin=False)
    _login_as_user(page, email=regular_email, password=regular_password)

    regular_response = page.request.post(
        f"{BASE_URL}/api/content-editable/save",
        form=payload,
        max_redirects=0,
    )
    assert not regular_response.ok, f"Expected non-admin save to be rejected, got HTTP {regular_response.status}"


def test_content_editor_survives_boosted_navigation(page: Page) -> None:
    """Each view gets one editor with the current user's existing permissions."""
    email, password = _create_verified_user(page, prefix="content-navigation", admin=True)
    _login_as_user(page, email=email, password=password)
    page.goto(f"{BASE_URL}/pakketten")
    # A full navigation creates a new Window; an HTMX swap keeps this sentinel alive.
    page.evaluate("window.htmxDocumentSentinel = true")
    for _ in range(2):
        expect(page.locator(".ct-ignition")).to_have_count(1)
        page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Home", exact=True).click()
        expect(page.locator("main h1")).to_contain_text("Van en voor scholen")
        page.get_by_role("navigation", name="Hoofdnavigatie").get_by_role("link", name="Catalogus", exact=True).click()
        expect(page.locator("main h1")).to_have_text("Pakketten & Producten")
        expect(page.locator(".ct-ignition")).to_have_count(1)
        assert page.evaluate("window.htmxDocumentSentinel") is True, (
            "Expected HTMX navigation to retain the current Window"
        )


def test_content_editor_reports_failed_save_after_logout(page: Page) -> None:
    """A logged-out editor must show a failed-save confirmation."""
    admin_email, admin_password = _create_verified_user(page, prefix="content-expired-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/pakketten")
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

    assert response_info.value.status != 200, "Expected a logged-out editor save to be rejected"
    expect(page.locator(".ct-flash--no")).to_be_attached()
    page.goto(f"{BASE_URL}/pakketten")
    assert unsaved_content not in page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html(), (
        "Expected rejected content to remain unsaved"
    )


def test_content_editor_admin_save_is_rendered_on_public_page(page: Page) -> None:
    """An admin save persists and replaces the matching public-page content region."""
    admin_email, admin_password = _create_verified_user(page, prefix="content-save-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/pakketten")

    region = page.locator(f"[data-name='{INTRODUCTION_REGION}']")
    original_content = region.inner_html()
    updated_content = f"<p>Playwright content {uuid.uuid4().hex}</p>"

    try:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: updated_content},
        )
        assert response.ok, f"Expected content save to succeed, got HTTP {response.status}"

        page.goto(f"{BASE_URL}/pakketten")
        assert page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html() == updated_content, (
            "Expected saved content on the public page"
        )
    finally:
        page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: original_content},
        )


def test_content_editor_preserves_blank_saved_content(page: Page) -> None:
    """A saved empty region must not fall back to its template default after reload."""
    admin_email, admin_password = _create_verified_user(page, prefix="content-blank-admin", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/pakketten")

    original_content = page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html()

    try:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: ""},
        )
        assert response.ok, f"Expected content save to succeed, got HTTP {response.status}"

        page.goto(f"{BASE_URL}/pakketten")
        assert page.locator(f"[data-name='{INTRODUCTION_REGION}']").inner_html() == "", (
            "Expected saved blank content after reload"
        )
    finally:
        page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={INTRODUCTION_REGION: original_content},
        )


def test_catalogue_participation_text_is_editable_and_shared_between_overviews(page: Page) -> None:
    """The asynchronously loaded card joins the editor and keeps one shared saved title."""
    admin_email, admin_password = _create_verified_user(page, prefix="participation-editor", admin=True)
    _login_as_user(page, email=admin_email, password=admin_password)
    page.goto(f"{BASE_URL}/pakketten")

    region = page.locator(f"[data-name='{PARTICIPATION_TITLE_REGION}']")
    expect(region).to_be_visible()
    original_content = region.inner_html()
    updated_title = f"Catalogusdeelname {uuid.uuid4().hex}"

    try:
        page.locator(".ct-ignition__button--edit").click()
        region.locator("h2").click()
        expect(region.locator("h2")).to_have_attribute("contenteditable", "")
        expect(page.locator(".catalogue-participation__empty-text")).to_be_visible()

        region.locator("h2").fill(updated_title)
        with page.expect_response(
            lambda response: (
                response.request.method == "POST" and response.url == f"{BASE_URL}/api/content-editable/save"
            ),
        ) as response_info:
            page.locator(".ct-ignition__button--confirm").click()

        assert response_info.value.ok

        for route in ("pakketten", "producten"):
            page.goto(f"{BASE_URL}/{route}")
            expect(region).to_have_text(updated_title)
            expect(page.locator(".catalogue-participation__empty-text")).to_be_hidden()
    finally:
        response = page.request.post(
            f"{BASE_URL}/api/content-editable/save",
            form={PARTICIPATION_TITLE_REGION: original_content},
        )
        assert response.ok
