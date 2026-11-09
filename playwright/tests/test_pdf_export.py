"""Browser coverage for PDF waiting and document navigation."""

from playwright.sync_api import Page, expect

from .auth_helpers import _create_verified_user, _login_as_user
from .settings import BASE_URL


def test_pdf_wait_uses_document_navigation(page: Page) -> None:
    """Refresh the document without requiring a client-side polling script."""
    email, password = _create_verified_user(page, prefix="pdf-loading", admin=True)
    _login_as_user(page, email=email, password=password)
    seeded = page.request.post(f"{BASE_URL}/test_seed_pdf_wait")
    gid_or_message = seeded.text()
    assert seeded.ok, gid_or_message
    pdf_url = f"{BASE_URL}/private/team/keuzecanvas/{gid_or_message}/visie.pdf"
    page.emulate_media(reduced_motion="reduce")
    with page.expect_request(f"{pdf_url}/wait") as refresh:
        page.goto(pdf_url)
        expect(page.get_by_role("heading", name="De PDF wordt gemaakt")).to_be_visible()
        expect(page.locator(".okl-pdf-wait__progress span")).to_have_css("animation-name", "none")
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    assert refresh.value.resource_type == "document"
    expect(page).to_have_url(f"{pdf_url}/wait")
